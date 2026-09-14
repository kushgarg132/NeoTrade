"""In-process + cross-worker pub/sub for the live socket.

Publishers (the engine loop, the suggestion store, the price pump) hand
events to the hub; each connection holds its own bounded queue and its own
set of topics. Delivery is never awaited on a slow consumer: a browser tab
that stops reading drops its oldest events instead of stalling the engine
that produced them.

With more than one Uvicorn worker, a message published on worker A must
reach a browser connected to worker B. Hub.publish() always broadcasts
through backend/broadcast.py; the actual per-connection delivery (Hub.deliver)
happens only in the subscriber loop (backend/broadcast.py's listen, wired up
in server.py's startup) -- whether that loop lives in this process or
another one. When no Redis is attached (tests, local dev), publish() falls
back to calling deliver() directly, since there's no subscriber loop to echo
the message back.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

from backend import broadcast

logger = logging.getLogger(__name__)

PRICE_PREFIX = "prices:"
DEFAULT_MAX_QUEUE = 100
EVENTS_CHANNEL = "ws:events"


class Connection:
    def __init__(self, user_id: str, max_queue: int = DEFAULT_MAX_QUEUE) -> None:
        self.user_id = user_id
        self.topics: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue)

    def subscribe(self, topics: Iterable[str]) -> None:
        self.topics.update(topics)

    def unsubscribe(self, topics: Iterable[str]) -> None:
        self.topics.difference_update(topics)

    def offer(self, message: dict) -> None:
        """Newest-wins: on a full queue the stalest event is discarded rather
        than the newest one, since a late price or P&L update is worth more
        than the one it replaced."""
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("dropping event for %s: queue still full", self.user_id)


class Hub:
    def __init__(self) -> None:
        self._connections: set[Connection] = set()
        self._redis = None

    def attach_redis(self, redis) -> None:
        """Called once at startup after backend.database.db connects -- the
        module-level `hub` singleton below is constructed before a Redis
        client exists."""
        self._redis = redis

    def connect(self, user_id: str, max_queue: int = DEFAULT_MAX_QUEUE) -> Connection:
        connection = Connection(user_id, max_queue=max_queue)
        self._connections.add(connection)
        return connection

    def disconnect(self, connection: Connection) -> None:
        self._connections.discard(connection)

    async def publish(self, user_id: str, topic: str, event: str, data) -> None:
        message = {
            "user_id": user_id,
            "topic": topic,
            "event": event,
            "data": data,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        await broadcast.publish(self._redis, EVENTS_CHANNEL, message)
        if self._redis is None:
            await self.deliver(message)

    async def deliver(self, message: dict) -> None:
        """Local delivery: pushes `message` onto every connection whose
        user_id and subscribed topics match. Called directly by publish()
        when there is no Redis, and by handle_broadcast_event (below) when
        the subscriber loop receives a message from the bus -- the two paths
        converge here so a message is only ever delivered by one piece of
        code."""
        for connection in list(self._connections):
            if connection.user_id == message["user_id"] and message["topic"] in connection.topics:
                connection.offer(message)

    def subscribed_symbols(self) -> set[str]:
        """Symbols any live connection on this worker is watching -- the
        price pump polls exactly these and nothing else. Local-only by
        design: two workers watching overlapping symbols poll twice, an
        accepted cost (see Phase 7 design doc's Non-goals)."""
        return {
            topic[len(PRICE_PREFIX):]
            for connection in self._connections
            for topic in connection.topics
            if topic.startswith(PRICE_PREFIX)
        }

    def users_on(self, topic: str) -> set[str]:
        return {c.user_id for c in self._connections if topic in c.topics}

    def users_watching(self, symbol: str) -> set[str]:
        topic = f"{PRICE_PREFIX}{symbol}"
        return {c.user_id for c in self._connections if topic in c.topics}


# The app's single hub; imported by publishers and by the socket route.
hub = Hub()


async def handle_broadcast_event(message: dict) -> None:
    """The "ws:events" handler registered with backend.broadcast.listen
    (wired up in server.py's startup, Task 5) -- delivers a message that
    arrived from the bus, whether it originated on this worker or another
    one."""
    await hub.deliver(message)
