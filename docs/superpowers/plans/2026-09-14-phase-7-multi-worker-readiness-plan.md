# Phase 7 (multi-worker readiness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FastAPI backend correct when run with more than one Uvicorn worker: cross-worker WS fan-out, a single daily scheduler pass, cross-worker run cancellation, a short-TTL deployment-wide LLM model cache, and a real per-user LLM model preference.

**Architecture:** A new `backend/broadcast.py` wraps Redis pub/sub (`publish`/`listen`) as the one cross-worker primitive; `ws/hub.py` and `routers/trading.py` both route through it instead of touching only local in-process state. The scheduler takes a Redis `SET NX PX` lock before its daily pass. The LLM model gets a short-TTL Mongo re-read for the deployment default, plus a `contextvars`-based ambient override for a per-user preference that needs no signature changes anywhere in the LLM call tree.

**Tech Stack:** Python 3.12, FastAPI, Motor (async Mongo), `redis.asyncio` (redis-py 8.1, `decode_responses=True`), `mongomock_motor` + `pytest-asyncio` (auto mode) for tests.

**Spec:** `docs/superpowers/specs/2026-09-12-phase-7-multi-worker-readiness-design.md`

## Global Constraints

- Redis client (`backend/database.py`) is built with `decode_responses=True` — every string read back from Redis (including pub/sub `channel`/`data`) is already `str`, never `bytes`.
- `redis` is `None` in every test and in local dev without Redis. Every new code path must degrade to direct/local behavior, never crash, when `redis is None` — same posture as `backend/ai/analyst_verdict.py`'s `get_cached_verdict`.
- No sticky routing, no leader-elected price pump, no per-user model for `/chat/message`, `/analyze/{symbol}`, or the scheduler's shared analyst-verdict/sentiment refresh, no confirmed round-trip for cross-worker cancellation. (See spec's Non-goals — do not build any of these.)
- Deployment-wide LLM model cache TTL: 30 seconds. Scheduler lock TTL: 2 hours (`7_200_000` ms).
- `pytest.ini` sets `asyncio_mode = auto` — `async def test_*` needs no `@pytest.mark.asyncio` decorator, though the existing suite uses it inconsistently; match whatever the file you're editing already does.
- Run tests with `cd backend && python -m pytest tests/<file>.py -v` (or `python -m pytest` for the whole suite before each commit).

---

### Task 1: `backend/broadcast.py` — the cross-worker event bus

**Files:**
- Create: `backend/broadcast.py`
- Test: `backend/tests/test_broadcast.py`

**Interfaces:**
- Produces: `async def publish(redis, channel: str, payload: dict) -> None` — no-op if `redis is None`, otherwise `await redis.publish(channel, json.dumps(payload))`.
- Produces: `async def listen(redis, handlers: dict[str, Callable[[dict], Awaitable[None]]]) -> None` — no-op (returns immediately) if `redis is None`; otherwise subscribes to every key in `handlers`, and for each received message of type `"message"`, JSON-decodes `data` and awaits `handlers[channel](payload)`. Runs forever (meant to be wrapped in `asyncio.create_task`). One handler raising must not kill the loop or block dispatch to the next message.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_broadcast.py
"""backend/broadcast.py: the cross-worker event bus. publish() and listen()
are the only two primitives -- everything else (ws/hub.py's fan-out,
routers/trading.py's cross-worker cancel) is built on top of these.
"""

import json

import pytest

from backend import broadcast


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages
        self.subscribed = []
        self.closed = False

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def listen(self):
        for message in self._messages:
            yield message

    async def close(self):
        self.closed = True


class _FakeRedis:
    def __init__(self, messages=None):
        self._messages = messages or []
        self.published = []

    def pubsub(self):
        return _FakePubSub(self._messages)

    async def publish(self, channel, data):
        self.published.append((channel, data))


async def test_publish_is_a_noop_when_redis_is_none():
    await broadcast.publish(None, "ws:events", {"a": 1})  # must not raise


async def test_publish_sends_the_payload_as_json():
    redis = _FakeRedis()

    await broadcast.publish(redis, "ws:events", {"symbol": "RELIANCE"})

    assert redis.published == [("ws:events", json.dumps({"symbol": "RELIANCE"}))]


async def test_listen_is_a_noop_when_redis_is_none():
    await broadcast.listen(None, {"ws:events": lambda payload: None})  # must return, not hang


async def test_listen_dispatches_to_the_handler_registered_for_the_channel():
    received = []

    async def handler(payload):
        received.append(payload)

    messages = [
        {"type": "subscribe", "channel": "ws:events", "data": 1},  # subscribe ack, must be ignored
        {"type": "message", "channel": "ws:events", "data": json.dumps({"symbol": "TCS"})},
    ]
    redis = _FakeRedis(messages)

    await broadcast.listen(redis, {"ws:events": handler})

    assert received == [{"symbol": "TCS"}]


async def test_listen_ignores_messages_on_unregistered_channels():
    received = []

    async def handler(payload):
        received.append(payload)

    messages = [{"type": "message", "channel": "some:other:channel", "data": json.dumps({})}]
    redis = _FakeRedis(messages)

    await broadcast.listen(redis, {"ws:events": handler})

    assert received == []


async def test_one_handler_failing_does_not_stop_dispatch_to_the_next_message():
    received = []

    async def flaky_handler(payload):
        if payload.get("boom"):
            raise RuntimeError("handler exploded")
        received.append(payload)

    messages = [
        {"type": "message", "channel": "ws:events", "data": json.dumps({"boom": True})},
        {"type": "message", "channel": "ws:events", "data": json.dumps({"ok": True})},
    ]
    redis = _FakeRedis(messages)

    await broadcast.listen(redis, {"ws:events": flaky_handler})

    assert received == [{"ok": True}]


async def test_listen_subscribes_to_every_handler_channel():
    redis = _FakeRedis([])
    pubsub_holder = {}

    original_pubsub = redis.pubsub

    def capturing_pubsub():
        ps = original_pubsub()
        pubsub_holder["ps"] = ps
        return ps

    redis.pubsub = capturing_pubsub

    await broadcast.listen(redis, {"ws:events": lambda p: None, "runs:cancel": lambda p: None})

    assert set(pubsub_holder["ps"].subscribed) == {"ws:events", "runs:cancel"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_broadcast.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.broadcast'`

- [ ] **Step 3: Write the implementation**

```python
# backend/broadcast.py
"""Cross-worker event bus: a thin wrapper over Redis pub/sub.

Two Uvicorn workers behind --workers N share nothing in-process. This is how
one worker's WS fan-out (backend/ws/hub.py) and run cancellation
(backend/routers/trading.py) reach the other. When `redis` is None (tests,
local dev without Redis) both functions degrade instead of crashing:
`publish` no-ops and `listen` returns immediately -- callers fall back to
whatever direct/local behavior they had before this module existed, the
same "degrade, don't crash" posture backend/ai/analyst_verdict.py's
get_cached_verdict already established for a missing cache.
"""

import json
import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


async def publish(redis, channel: str, payload: dict) -> None:
    if redis is None:
        return
    try:
        await redis.publish(channel, json.dumps(payload))
    except Exception as exc:
        logger.warning("broadcast publish to %s failed: %s", channel, exc)


async def listen(redis, handlers: dict[str, Callable[[dict], Awaitable[None]]]) -> None:
    """Subscribes once to every channel in `handlers` and dispatches each
    received message to the handler registered for its channel. Runs
    forever -- start it as a background asyncio.Task. Returns immediately,
    doing nothing, if `redis` is None."""
    if redis is None:
        return

    pubsub = redis.pubsub()
    await pubsub.subscribe(*handlers.keys())
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            handler = handlers.get(message["channel"])
            if handler is None:
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                logger.warning("broadcast message on %s was not valid JSON", message["channel"])
                continue
            try:
                await handler(payload)
            except Exception as exc:
                logger.exception("broadcast handler for %s failed: %s", message["channel"], exc)
    finally:
        await pubsub.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_broadcast.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/broadcast.py backend/tests/test_broadcast.py
git commit -m "feat: add backend/broadcast.py -- Redis pub/sub cross-worker event bus (Phase 7)"
```

---

### Task 2: `ws/hub.py` fan-out through the broadcast bus

**Files:**
- Modify: `backend/ws/hub.py`
- Test: `backend/tests/test_ws_hub.py` (add tests; existing tests stay unmodified and must still pass)

**Interfaces:**
- Consumes: `backend.broadcast.publish(redis, channel: str, payload: dict) -> None` (Task 1).
- Produces: `Hub.attach_redis(redis) -> None` — sets the instance's Redis client after construction (the module-level `hub` singleton is built before `backend.database.db` has a live client).
- Produces: `Hub.deliver(message: dict) -> None` (async) — local-only delivery to every connection matching `message["user_id"]`/`message["topic"]`. This is the method both `Hub.publish` (when `redis is None`) and the new module-level `handle_broadcast_event` (Task 5) call.
- Produces: `async def handle_broadcast_event(message: dict) -> None` (module-level, in `backend/ws/hub.py`) — the `"ws:events"` handler `broadcast.listen` will dispatch to (wired up in Task 5).
- `Hub.publish(user_id, topic, event, data)` keeps its existing signature and behavior when no Redis is attached (delivers locally, synchronously, before returning) — every existing caller (`ws/pump.py`, `routers/trading.py`, `ws/publish.py`) needs zero changes.

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `backend/tests/test_ws_hub.py` (keep everything above unchanged):

```python
from backend.ws.hub import Hub, handle_broadcast_event


class _FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, data):
        self.published.append((channel, data))


@pytest.mark.asyncio
async def test_publish_broadcasts_instead_of_delivering_locally_when_redis_is_attached():
    hub = Hub()
    fake_redis = _FakeRedis()
    hub.attach_redis(fake_redis)
    connection = hub.connect("alice")
    connection.subscribe(["trades"])

    await hub.publish("alice", "trades", "opened", {"symbol": "TCS"})

    assert fake_redis.published, "publish() must call broadcast.publish when a redis is attached"
    assert connection.queue.empty(), "no direct local delivery -- that happens via the subscriber loop"


@pytest.mark.asyncio
async def test_deliver_pushes_to_every_matching_connection():
    hub = Hub()
    alice = hub.connect("alice")
    alice.subscribe(["trades"])
    bob = hub.connect("bob")
    bob.subscribe(["trades"])

    message = {"user_id": "alice", "topic": "trades", "event": "opened", "data": {}, "ts": "x"}
    await hub.deliver(message)

    assert not alice.queue.empty()
    assert bob.queue.empty()


@pytest.mark.asyncio
async def test_handle_broadcast_event_delivers_via_the_module_level_hub():
    from backend.ws.hub import hub as real_hub

    connection = real_hub.connect("alice")
    connection.subscribe(["trades"])
    try:
        message = {"user_id": "alice", "topic": "trades", "event": "opened", "data": {}, "ts": "x"}
        await handle_broadcast_event(message)

        assert not connection.queue.empty()
    finally:
        real_hub.disconnect(connection)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ws_hub.py -v`
Expected: FAIL — `AttributeError: 'Hub' object has no attribute 'attach_redis'` (and `deliver`, and `ImportError` for `handle_broadcast_event`).

- [ ] **Step 3: Write the implementation**

Replace `backend/ws/hub.py` in full:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ws_hub.py -v`
Expected: PASS (all original tests + 3 new ones)

Also run `cd backend && python -m pytest tests/test_ws_routes.py -v` — those tests construct `Hub()` directly and call `hub.publish(...)`; with no `attach_redis` call, `self._redis` stays `None`, so `publish()` falls through to local `deliver()` exactly as before. Expected: PASS unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend/ws/hub.py backend/tests/test_ws_hub.py
git commit -m "feat: route ws/hub.py fan-out through the cross-worker broadcast bus (Phase 7)"
```

---

### Task 3: `scheduler.py` distributed lock

**Files:**
- Modify: `backend/scheduler.py`
- Test: `backend/tests/test_scheduler.py` (add tests; existing tests unmodified)

**Interfaces:**
- Produces: `LOCK_KEY = "scheduler:daily_lock"`, `LOCK_TTL_MS = 7_200_000` (module constants).
- Produces: `async def _run_locked(db, redis) -> Optional[dict]` — when `redis is None`, always runs `run_daily_jobs(db, redis=redis)` and returns its result (matches every existing test's calling convention). When `redis` is given: attempts `SET LOCK_KEY <token> NX PX LOCK_TTL_MS`; if that fails (lock already held), logs and returns `None` without running the pass; if it succeeds, runs `run_daily_jobs`, then releases the lock only if it still holds it (`GET` the key, `DELETE` only if the value still matches this call's own token).
- `scheduler_loop` calls `_run_locked` instead of `run_daily_jobs` directly. `run_daily_jobs` itself is untouched — every existing test that calls it directly keeps passing unmodified.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_scheduler.py`, near the bottom (after the existing analyst-verdict section), keeping the existing `from unittest.mock import AsyncMock` import:

```python
from unittest.mock import ANY

# ---------------------------------------------------------------------------
# Distributed lock (Phase 7)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_redis_none_always_runs_the_pass_with_no_lock(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    result = await scheduler._run_locked(mongo, None)

    assert result is not None
    assert result["users"] == 0


@pytest.mark.asyncio
async def test_a_second_worker_skips_the_pass_while_the_lock_is_held(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=None)  # NX failed: someone else holds it

    result = await scheduler._run_locked(mongo, redis)

    assert result is None
    redis.set.assert_awaited_once_with(scheduler.LOCK_KEY, ANY, nx=True, px=scheduler.LOCK_TTL_MS)


@pytest.mark.asyncio
async def test_the_lock_is_released_after_the_pass_completes(mongo, monkeypatch):
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)
    monkeypatch.setattr(scheduler.uuid, "uuid4", lambda: "fixed-token")

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value="fixed-token")

    result = await scheduler._run_locked(mongo, redis)

    assert result is not None
    redis.delete.assert_awaited_once_with(scheduler.LOCK_KEY)


@pytest.mark.asyncio
async def test_a_worker_never_releases_a_lock_it_no_longer_owns(mongo, monkeypatch):
    """The TTL can expire and another worker can acquire the lock before this
    worker's release runs; the release must check ownership first."""
    async def fake_scan(db, user_id, universe, **kwargs):
        return []
    monkeypatch.setattr(scheduler, "scan_universe", fake_scan)
    monkeypatch.setattr(scheduler.uuid, "uuid4", lambda: "fixed-token")

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value="someone-elses-token")

    await scheduler._run_locked(mongo, redis)

    redis.delete.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `AttributeError: module 'backend.scheduler' has no attribute '_run_locked'`

- [ ] **Step 3: Write the implementation**

In `backend/scheduler.py`, add these two module constants right after the existing `MAX_SENTIMENT_REFRESH = 20` line:

```python
# Distributed lock so two workers running scheduler_loop concurrently
# produce exactly one daily pass, not two.
LOCK_KEY = "scheduler:daily_lock"
LOCK_TTL_MS = 2 * 60 * 60 * 1000  # 2 hours: covers a full pass, including
# per-user LLM calls, rather than a heartbeat/renewal loop -- a crashed
# holder self-heals at TTL expiry instead of leaving the pass permanently
# blocked.
```

Add this new function right after `run_daily_jobs` (before `_default_spot_lookup`):

```python
async def _run_locked(db, redis) -> Optional[dict]:
    """Acquires a Redis lock before running the daily pass. Returns None
    (pass skipped) if another worker already holds it. When `redis` is None
    the lock is skipped and the pass always runs -- matches every existing
    test's redis=None/mocked-redis calling convention for run_daily_jobs."""
    if redis is None:
        return await run_daily_jobs(db, redis=redis)

    token = str(uuid.uuid4())
    acquired = await redis.set(LOCK_KEY, token, nx=True, px=LOCK_TTL_MS)
    if not acquired:
        logger.info("daily pass already running on another worker, skipping")
        return None

    try:
        return await run_daily_jobs(db, redis=redis)
    finally:
        # Only release if we still hold it -- never delete a lock some other
        # worker has since acquired after this one's TTL expired.
        current = await redis.get(LOCK_KEY)
        if current == token:
            await redis.delete(LOCK_KEY)
```

Change `scheduler_loop` to call `_run_locked` instead of `run_daily_jobs`:

```python
async def scheduler_loop(db, redis=None) -> None:
    while True:
        await asyncio.sleep(seconds_until_next_run(datetime.now(timezone.utc)))
        try:
            await _run_locked(db, redis)
        except Exception as exc:
            # Never let one bad day kill the loop for every day after it.
            logger.exception("daily pass failed: %s", exc)
```

Also delete the stale `ponytail:` note at the top of the file (lines 8-10: `"ponytail: one process owns this loop. If the backend is ever run with more than one worker, they will all fire it -- take a Redis lock before the pass at that point."`) since this task is exactly that Redis lock landing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_scheduler.py -v`
Expected: PASS (all original tests + 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat: scheduler.py takes a Redis lock so only one worker runs the daily pass (Phase 7)"
```

---

### Task 4: `routers/trading.py` cross-worker run cancellation

**Files:**
- Modify: `backend/routers/trading.py`
- Test: `backend/tests/test_trading_router.py` (add tests; existing tests unmodified)

**Interfaces:**
- Consumes: `backend.broadcast.publish(redis, channel, payload)` (Task 1).
- Produces: `async def _cancel_local(run_id: str) -> bool` — cancels and awaits the task in `_RUNS[run_id]` if present, pops it, returns `True`; returns `False` if not found locally. (Extracted from the old `stop_background_run` body so both call sites share one cancel implementation.)
- `stop_background_run(run_id)` keeps its existing signature/return type. New behavior: if `_cancel_local` finds nothing locally AND `backend.database.db.redis` is not `None`, it publishes to `"runs:cancel"` and returns `True` (optimistic, per spec). If `db.redis` is `None` (tests, local dev), it returns `False` exactly as before — the existing `test_stop_unknown_run_id_returns_false` test needs no change.
- Produces: `async def handle_cancel_broadcast(payload: dict) -> None` (module-level) — the `"runs:cancel"` handler (wired up in Task 5): calls `_cancel_local(payload.get("run_id", ""))` and ignores the result.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_trading_router.py`, right after the existing three `start_background_run`/`stop_background_run` tests (after line 68's `test_stop_unknown_run_id_returns_false`), keeping the existing `_forever` helper:

```python
import json


@pytest.mark.asyncio
async def test_stop_broadcasts_when_the_run_is_not_local_and_redis_is_configured(monkeypatch):
    from backend.database import db as real_db

    class _FakeRedis:
        def __init__(self):
            self.published = []

        async def publish(self, channel, data):
            self.published.append((channel, data))

    fake_redis = _FakeRedis()
    monkeypatch.setattr(real_db, "redis", fake_redis)

    stopped = await trading.stop_background_run("elsewhere-run")

    assert stopped is True
    assert len(fake_redis.published) == 1
    channel, payload = fake_redis.published[0]
    assert channel == "runs:cancel"
    assert json.loads(payload) == {"run_id": "elsewhere-run"}


@pytest.mark.asyncio
async def test_cancel_broadcast_handler_cancels_a_matching_local_task():
    run_id = trading.start_background_run(_forever())
    try:
        await asyncio.wait_for(trading.handle_cancel_broadcast({"run_id": run_id}), timeout=2.0)
        assert run_id not in trading._RUNS
    finally:
        trading._RUNS.pop(run_id, None)


@pytest.mark.asyncio
async def test_cancel_broadcast_handler_ignores_a_run_id_it_does_not_own():
    await trading.handle_cancel_broadcast({"run_id": "no-such-run"})  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_trading_router.py -v -k "broadcast"`
Expected: FAIL with `AttributeError: module 'backend.routers.trading' has no attribute 'handle_cancel_broadcast'`

- [ ] **Step 3: Write the implementation**

Add `from backend import broadcast` to the imports at the top of `backend/routers/trading.py` (alongside the other `from backend...` imports).

Replace the existing `stop_background_run` function (lines 160-170) with:

```python
async def _cancel_local(run_id: str) -> bool:
    task = _RUNS.get(run_id)
    if task is None:
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    _RUNS.pop(run_id, None)
    return True


async def stop_background_run(run_id: str) -> bool:
    if await _cancel_local(run_id):
        return True

    from backend.database import db as _db
    if _db.redis is None:
        return False
    await broadcast.publish(_db.redis, "runs:cancel", {"run_id": run_id})
    return True


async def handle_cancel_broadcast(payload: dict) -> None:
    """The "runs:cancel" handler registered with backend.broadcast.listen
    (wired up in server.py's startup, Task 5). Fire-and-forget: the caller
    that published this already confirmed via RunStore that the run is
    genuinely ACTIVE, so "no local task with this id" here just means it
    belongs to a different worker (or already finished -- an existing,
    harmless race)."""
    await _cancel_local(payload.get("run_id", ""))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_trading_router.py -v`
Expected: PASS (all original tests + 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/routers/trading.py backend/tests/test_trading_router.py
git commit -m "feat: trading.py falls back to a cross-worker broadcast to cancel a run (Phase 7)"
```

---

### Task 5: Wire the broadcast bus into `server.py` startup

**Files:**
- Modify: `backend/server.py`

**Interfaces:**
- Consumes: `Hub.attach_redis` (Task 2), `handle_broadcast_event` (Task 2), `handle_cancel_broadcast` (Task 4), `broadcast.listen` (Task 1).
- No new interfaces produced — this task only wires existing pieces together at startup. No unit test: it's exercised by every test in Tasks 1-4 already, and the "Done when" checks at the end of this plan verify it end-to-end.

- [ ] **Step 1: Add imports**

At the top of `backend/server.py`, add `import asyncio` (currently missing) after the existing `import sys` / `import os` lines, and add two new imports alongside the existing `from backend import scheduler` line:

```python
from backend import broadcast
from backend.ws.hub import hub, handle_broadcast_event
```

- [ ] **Step 2: Start the broadcast listener at startup**

In `startup_db_client` (`backend/server.py`), right after `await db.connect_to_database()` and its log line, add:

```python
    hub.attach_redis(db.redis)
    from backend.routers.trading import handle_cancel_broadcast
    asyncio.create_task(broadcast.listen(db.redis, {
        "ws:events": handle_broadcast_event,
        "runs:cancel": handle_cancel_broadcast,
    }))
```

(The `handle_cancel_broadcast` import is local, matching this file's existing style of importing `backend.routers.trading` further down the module — importing it at the top would work too, but this avoids reordering the file's existing import block.)

- [ ] **Step 3: Verify the app still starts**

Run: `cd backend && python -c "import server"` — must import without error (no live DB/Redis needed for a bare import; `startup_db_client` doesn't run until Uvicorn calls it).

Then run the full test suite to confirm nothing broke:

Run: `cd backend && python -m pytest -v`
Expected: PASS, same count as before this task plus the tests added in Tasks 1-4.

- [ ] **Step 4: Commit**

```bash
git add backend/server.py
git commit -m "feat: start the cross-worker broadcast listener at app startup (Phase 7)"
```

---

### Task 6: Deployment-wide LLM model — short-TTL cache, `get_llm()` goes async

**Files:**
- Modify: `backend/app_settings.py`
- Modify: `backend/llm.py`
- Modify: `backend/components/chat/agent.py`
- Test: `backend/tests/test_app_settings.py` (rewrite the model-cache tests; the three basic `AppSettingsStore` tests at the top stay as-is)

**Interfaces:**
- Produces: `async def current_llm_model(db=None) -> str` (was sync) — `db` is optional and defaults to the real `backend.database.db.db` singleton (tests pass a `mongomock_motor` db directly). Re-reads Mongo via `AppSettingsStore(db).get_llm_model()` only when the in-process cache is older than 30 seconds (`time.monotonic()`-based); otherwise returns the cached value. Falls back to `settings.OMNIROUTE_MODEL` when nothing is cached/stored.
- `AppSettingsStore.set_llm_model` and `AppSettingsStore.load_into_cache` keep writing `_cached_llm_model` (so the process that changed it sees the new value on its very next call, no restart needed) and additionally reset `_cache_loaded_at = time.monotonic()` so that same process doesn't immediately re-hit Mongo.
- `LLMService.get_llm()` becomes `async def get_llm(self)`, calling `model = await current_llm_model()` (the per-user override lands in Task 7; for this task it's always the deployment default). `LLMService.get_completion` updates its call site to `llm = await self.get_llm()`.
- `ChatAgent._build_agent` becomes `async def _build_agent(self)`, calling `llm = await llm_service.get_llm()`. Both of its callers (`stream_message`, `processed_message`) change `agent = self._build_agent()` to `agent = await self._build_agent()`.

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_app_settings.py` in full:

```python
"""Deployment-wide settings in Mongo, replacing the .env rewriting.

current_llm_model() is called from LLMService.get_llm() on (effectively)
every LLM request, so it can't read Mongo every time -- but with more than
one worker, a process-local cache that only refreshes when THIS process
calls set_llm_model means a second worker never sees an admin's change. The
fix is a short TTL: re-read Mongo at most once every 30 seconds.
"""

from mongomock_motor import AsyncMongoMockClient

from backend import app_settings as app_settings_module
from backend.app_settings import AppSettingsStore, current_llm_model


def _store():
    return AppSettingsStore(AsyncMongoMockClient()["test_db"])


async def test_model_starts_unset():
    assert await _store().get_llm_model() is None


async def test_setting_the_model_persists_it():
    store = _store()
    await store.set_llm_model("aug/sonnet5-high")
    assert await store.get_llm_model() == "aug/sonnet5-high"


async def test_setting_the_model_replaces_rather_than_accumulates():
    store = _store()
    await store.set_llm_model("first")
    await store.set_llm_model("second")

    assert await store.get_llm_model() == "second"
    assert await store.collection.count_documents({}) == 1


async def test_current_model_falls_back_to_the_configured_default(monkeypatch):
    from backend.configs import settings as settings_module

    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    monkeypatch.setattr(settings_module.settings, "OMNIROUTE_MODEL", "env/default-model")

    mongo = AsyncMongoMockClient()["test_db"]
    assert await current_llm_model(db=mongo) == "env/default-model"


async def test_saving_a_model_takes_effect_immediately_in_this_process(monkeypatch):
    """get_llm() is called per request and awaits current_llm_model(), which
    caches for 30s -- but set_llm_model resets that clock in THIS process, so
    the admin who just changed it sees the new value on their very next
    call, no restart or TTL wait needed."""
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()

    await store.set_llm_model("aug/sonnet5-high")

    assert await current_llm_model(db=store._db) == "aug/sonnet5-high"


async def test_the_stored_model_is_loaded_at_startup(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()
    await store.collection.update_one(
        {"_id": "singleton"}, {"$set": {"llm_model": "persisted/model"}}, upsert=True
    )

    await store.load_into_cache()

    assert await current_llm_model(db=store._db) == "persisted/model"


async def test_a_read_within_the_ttl_window_does_not_touch_mongo_again(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()
    await store.set_llm_model("aug/sonnet5-high")

    fake_time = [1_000.0]
    monkeypatch.setattr(app_settings_module.time, "monotonic", lambda: fake_time[0])
    # Force the cache to look stale once, then observe it does NOT refetch
    # again for a second read 5s later (well inside the 30s TTL).
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", fake_time[0])

    calls = []
    real_get = AppSettingsStore.get_llm_model

    async def counting_get(self):
        calls.append(1)
        return await real_get(self)

    monkeypatch.setattr(AppSettingsStore, "get_llm_model", counting_get)

    fake_time[0] += 5
    first = await current_llm_model(db=store._db)
    fake_time[0] += 5
    second = await current_llm_model(db=store._db)

    assert first == second == "aug/sonnet5-high"
    assert calls == []  # still within the TTL window from the fixture's own set_llm_model reset


async def test_a_read_past_the_ttl_window_refetches_from_mongo(monkeypatch):
    monkeypatch.setattr(app_settings_module, "_cached_llm_model", None)
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", 0.0)
    store = _store()
    await store.set_llm_model("first")

    fake_time = [1_000.0]
    monkeypatch.setattr(app_settings_module.time, "monotonic", lambda: fake_time[0])
    monkeypatch.setattr(app_settings_module, "_cache_loaded_at", fake_time[0])

    first = await current_llm_model(db=store._db)
    await store.collection.update_one({"_id": "singleton"}, {"$set": {"llm_model": "second"}})
    fake_time[0] += 31  # past the 30s TTL window

    second = await current_llm_model(db=store._db)

    assert first == "first"
    assert second == "second"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_app_settings.py -v`
Expected: FAIL — `TypeError: object str can't be used in 'await' expression` (existing sync `current_llm_model` called with `await`).

- [ ] **Step 3: Write the implementation**

Replace `backend/app_settings.py` in full:

```python
"""Deployment-wide settings that used to be rewritten into .env at runtime
(collection `app_settings`, one document).

Writing .env from a request mutated shared process state, did not survive
more than one worker, and was reachable by anyone signed in. These settings
are genuinely deployment-wide rather than per-user, so they stay shared --
but they live in the database and only an admin may change them.

current_llm_model() is called from LLMService.get_llm() on effectively every
LLM request. With one worker, caching it in-process and refreshing only on
a local set_llm_model call was enough. With more than one, a second worker
would keep serving the stale value until it restarted -- so the cache now
has a short TTL (re-read Mongo at most once every 30s) instead of relying
purely on a local write to invalidate it.
"""

import time
from datetime import datetime, timezone
from typing import Optional

_DOC_ID = "singleton"
_TTL_SECONDS = 30

_cached_llm_model: Optional[str] = None
_cache_loaded_at: float = 0.0


async def current_llm_model(db=None) -> str:
    from backend.configs.settings import settings

    global _cached_llm_model, _cache_loaded_at

    if time.monotonic() - _cache_loaded_at >= _TTL_SECONDS:
        if db is None:
            from backend.database import db as _db
            db = _db.db
        _cached_llm_model = await AppSettingsStore(db).get_llm_model()
        _cache_loaded_at = time.monotonic()

    return _cached_llm_model or settings.OMNIROUTE_MODEL


class AppSettingsStore:
    def __init__(self, db) -> None:
        self._db = db

    @property
    def collection(self):
        return self._db["app_settings"]

    async def get_llm_model(self) -> Optional[str]:
        doc = await self.collection.find_one({"_id": _DOC_ID})
        return (doc or {}).get("llm_model")

    async def set_llm_model(self, model: str) -> None:
        global _cached_llm_model, _cache_loaded_at
        await self.collection.update_one(
            {"_id": _DOC_ID},
            {"$set": {"llm_model": model, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        _cached_llm_model = model
        _cache_loaded_at = time.monotonic()

    async def load_into_cache(self) -> None:
        global _cached_llm_model, _cache_loaded_at
        _cached_llm_model = await self.get_llm_model()
        _cache_loaded_at = time.monotonic()
```

In `backend/llm.py`:
- Change `def get_llm(self):` to `async def get_llm(self):` and change `model=current_llm_model(),` to `model=model,` where `model` is computed as the first line of the method body: `model = current_llm_model()` → after Task 7 this becomes the override-aware line, but for this task alone it's simply:

```python
    async def get_llm(self):
        """Returns a MultiKeyChain wrapping ChatOpenAI instances pointed at the OmniRoute gateway"""
        from langchain_openai import ChatOpenAI

        keys = self.keys
        if not keys:
            return None

        model = await current_llm_model()
        llms = []
        for key in keys:
            llms.append(ChatOpenAI(
                model=model,
                api_key=key,
                base_url=settings.OMNIROUTE_BASE_URL,
                temperature=0.0,
                max_retries=0  # We handle retries via rotation
            ))

        if len(llms) == 1:
            return llms[0]

        return MultiKeyChain(llms)
```

- Change `get_completion`'s `llm = self.get_llm()` to `llm = await self.get_llm()`.

In `backend/components/chat/agent.py`:

```python
    async def _build_agent(self):
        """Built fresh per call, not cached on self: llm_service.get_llm()
        reads the deployment-wide model (or a per-user override, see
        backend/llm.py's use_model) on every call, so a change takes effect
        on the next message instead of needing a restart."""
        llm = await llm_service.get_llm()
        if not llm:
            logger.warning("ChatAgent: No LLM available (API Key missing?)")
            return None
        return create_react_agent(llm, self.tools)
```

Change both call sites (`stream_message` and `processed_message`) from `agent = self._build_agent()` to `agent = await self._build_agent()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_app_settings.py -v`
Expected: PASS (9 tests)

Run the full suite to catch any other caller of the now-async `get_llm`/`current_llm_model`:

Run: `cd backend && python -m pytest -v`
Expected: PASS (grep confirmed earlier that `llm.py` and `components/chat/agent.py` are the only call sites of `get_llm`/`current_llm_model` outside tests, so no other file should break).

- [ ] **Step 5: Commit**

```bash
git add backend/app_settings.py backend/llm.py backend/components/chat/agent.py backend/tests/test_app_settings.py
git commit -m "feat: short-TTL cross-worker cache for the deployment LLM model, get_llm() goes async (Phase 7)"
```

---

### Task 7: Per-user LLM model override (`contextvars`) + wiring

**Files:**
- Modify: `backend/llm.py`
- Modify: `backend/ws/routes.py`
- Modify: `backend/suggestions/thesis.py`
- Modify: `backend/tests/test_ws_routes.py` (the `client` fixture needs a Mongo db attached; add two new tests)
- Create: `backend/tests/test_llm.py`
- Create: `backend/tests/test_thesis.py`

**Interfaces:**
- Produces (in `backend/llm.py`): `use_model(model: Optional[str])` — a context manager (via `contextlib.contextmanager`) that sets an ambient `contextvars.ContextVar` for the duration of the `with` block; a no-op when `model` is `None`. `LLMService.get_llm()` becomes `model = _model_override.get() or await current_llm_model()`.
- Consumes (in `ws/routes.py` and `suggestions/thesis.py`): `backend.llm.use_model`, `backend.prefs.PrefsStore.get(user_id) -> dict` (existing; `omniroute_model` key already in `DEFAULTS`).
- No changes anywhere in `ResearchAgent`, `AnalystAgent`, `analyst/sentiment.py`, `analyst/events.py`, `master/search.py`, or `instruments/resolve.py` — verifying that stays true (their existing tests pass unmodified) is part of this task's own verification.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_llm.py`:

```python
"""backend/llm.py: the per-user model override (use_model) and how
get_llm() picks a model -- the override first if one is set for the current
task, the deployment default (backend.app_settings.current_llm_model)
otherwise.
"""

import asyncio

import pytest

from backend import llm as llm_module
from backend.llm import LLMService, use_model


class _FakeChatOpenAI:
    def __init__(self, model, **kwargs):
        self.model = model

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr("langchain_openai.ChatOpenAI", _FakeChatOpenAI)
    svc = LLMService()
    svc.keys = ["k1"]
    return svc


@pytest.fixture(autouse=True)
def _default_model(monkeypatch):
    async def fake_current_llm_model():
        return "deployment/default"

    monkeypatch.setattr(llm_module, "current_llm_model", fake_current_llm_model)


async def test_get_llm_uses_the_deployment_default_with_no_override(service):
    llm = await service.get_llm()
    assert llm.model == "deployment/default"


async def test_get_llm_uses_the_override_inside_a_with_block(service):
    with use_model("user/preferred-model"):
        llm = await service.get_llm()
    assert llm.model == "user/preferred-model"


async def test_get_llm_falls_back_outside_the_with_block(service):
    with use_model("user/preferred-model"):
        pass
    llm = await service.get_llm()
    assert llm.model == "deployment/default"


async def test_use_model_none_is_a_noop(service):
    with use_model(None):
        llm = await service.get_llm()
    assert llm.model == "deployment/default"


async def test_nested_use_model_restores_the_outer_value_on_exit(service):
    with use_model("outer/model"):
        with use_model("inner/model"):
            inner = await service.get_llm()
        after_inner = await service.get_llm()
    assert inner.model == "inner/model"
    assert after_inner.model == "outer/model"


async def test_override_set_in_a_parent_task_is_visible_in_a_child_task(service):
    """The mechanism analyze_sentiment_logic's per-article asyncio.gather
    fan-out relies on: a ContextVar set before create_task/gather is copied
    into the new Task's context at creation time, not shared live. This is
    the one test that would catch a wrong assumption about that
    propagation."""
    seen = {}

    async def child():
        seen["model"] = (await service.get_llm()).model

    with use_model("parent/model"):
        await asyncio.create_task(child())

    assert seen["model"] == "parent/model"
```

Create `backend/tests/test_thesis.py`:

```python
"""backend/suggestions/thesis.py: attaching an LLM-derived rationale to
fresh suggestions using the user's own saved model preference, if any.
"""

from mongomock_motor import AsyncMongoMockClient

from backend.llm import _model_override
from backend.prefs import PrefsStore
from backend.suggestions.store import SuggestionStore
from backend.suggestions.thesis import attach_theses


def _mongo():
    return AsyncMongoMockClient()["test_db"]


class _Report:
    def __init__(self, thesis):
        self.thesis = thesis
        self.analyst_summary = ""


class _RecordingAgent:
    def __init__(self, thesis="Fine business."):
        self.thesis = thesis
        self.seen_models = []

    async def run(self, symbol):
        self.seen_models.append(_model_override.get())
        return _Report(self.thesis)


async def _seed_suggestion(mongo, user_id, suggestion_id, symbol):
    await mongo["suggestions"].insert_one({
        "id": suggestion_id, "user_id": user_id, "symbol": symbol, "mode": "LONGTERM",
        "status": "PENDING", "ai_thesis": None,
    })


async def test_attaches_a_thesis_using_the_users_preferred_model():
    mongo = _mongo()
    await _seed_suggestion(mongo, "alice", "s1", "RELIANCE")
    await PrefsStore(mongo).update("alice", {"omniroute_model": "user/preferred"})
    agent = _RecordingAgent()

    attached = await attach_theses(mongo, "alice", [{"id": "s1", "symbol": "RELIANCE"}], agent=agent)

    assert attached == 1
    assert agent.seen_models == ["user/preferred"]
    assert (await SuggestionStore(mongo).get("alice", "s1"))["ai_thesis"] == "Fine business."


async def test_no_saved_preference_is_a_noop_override():
    mongo = _mongo()
    await _seed_suggestion(mongo, "alice", "s1", "RELIANCE")
    agent = _RecordingAgent()

    await attach_theses(mongo, "alice", [{"id": "s1", "symbol": "RELIANCE"}], agent=agent)

    assert agent.seen_models == [None]
```

In `backend/tests/test_ws_routes.py`, update the `client` fixture to attach a Mongo db (so the new `PrefsStore` lookup in `_stream_analysis`/`_stream_chat` has something to read), and add `import asyncio` near the top of the file:

```python
import asyncio
```

```python
@pytest.fixture
def client(monkeypatch, hub):
    from mongomock_motor import AsyncMongoMockClient

    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(ws_routes.db, "db", mongo)

    async def fake_authenticate(token):
        return _USER if token == "good-token" else None

    monkeypatch.setattr(ws_routes, "authenticate_token", fake_authenticate)
    monkeypatch.setattr(ws_routes.settings, "CORS_ALLOWED_ORIGINS", [ALLOWED_ORIGIN])

    app = FastAPI()
    app.include_router(ws_routes.router, prefix="/api/v1")
    return TestClient(app)
```

Add these two new tests at the bottom of `backend/tests/test_ws_routes.py`:

```python
def test_analysis_uses_the_users_saved_model_preference(client, monkeypatch):
    from backend.prefs import PrefsStore

    asyncio.run(PrefsStore(ws_routes.db.db).update("alice", {"omniroute_model": "user/preferred"}))

    seen_model = {}

    class _Report:
        def model_dump(self):
            return {"symbol": "RELIANCE"}

    class _Agent:
        async def run(self, symbol):
            from backend.llm import _model_override
            seen_model["model"] = _model_override.get()
            return _Report()

    monkeypatch.setattr("backend.research.graph.ResearchAgent", lambda: _Agent())

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "analyze", "symbol": "RELIANCE", "req_id": "r3"})
        socket.receive_json()  # started
        socket.receive_json()  # report

    assert seen_model["model"] == "user/preferred"


def test_chat_uses_the_users_saved_model_preference(client, monkeypatch):
    from backend.prefs import PrefsStore

    asyncio.run(PrefsStore(ws_routes.db.db).update("alice", {"omniroute_model": "user/preferred"}))

    seen_model = {}

    class _ChatAgent:
        async def stream_message(self, message, history):
            from backend.llm import _model_override
            seen_model["model"] = _model_override.get()
            yield {"type": "content", "data": "hi"}

    monkeypatch.setattr("backend.components.chat.agent.chat_agent", _ChatAgent())

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "chat", "message": "hi", "req_id": "c2"})
        socket.receive_json()  # content
        socket.receive_json()  # done

    assert seen_model["model"] == "user/preferred"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm.py tests/test_thesis.py -v`
Expected: FAIL — `ImportError: cannot import name 'use_model' from 'backend.llm'` and `ImportError: cannot import name '_model_override' from 'backend.llm'`.

Run: `cd backend && python -m pytest tests/test_ws_routes.py -v -k "preference"`
Expected: FAIL — `KeyError` or assertion mismatch (`_stream_analysis`/`_stream_chat` don't set the override yet).

- [ ] **Step 3: Write the implementation**

In `backend/llm.py`, add near the top (after the existing imports, before `MultiKeyChain`):

```python
import contextlib
import contextvars

_model_override: contextvars.ContextVar["Optional[str]"] = contextvars.ContextVar(
    "model_override", default=None
)


@contextlib.contextmanager
def use_model(model: Optional[str]):
    """Ambient per-user model override for the duration of a `with` block.
    A no-op when `model` is None, so callers with no saved preference don't
    need to branch. Every nested LLMService.get_completion call anywhere in
    the tree (ResearchAgent, AnalystAgent, sentiment/events classifiers,
    resolve_symbol, ...) picks this up transparently through get_llm() --
    no signature changes needed in any of those modules. Propagates
    correctly into a child asyncio.Task created via create_task/gather from
    inside the `with` block, since each new Task captures a copy of the
    current context at creation time."""
    token = _model_override.set(model)
    try:
        yield
    finally:
        _model_override.reset(token)
```

Change `LLMService.get_llm`'s model line from `model = await current_llm_model()` to:

```python
        model = _model_override.get() or await current_llm_model()
```

In `backend/ws/routes.py`, update `_stream_analysis`:

```python
async def _stream_analysis(connection, symbol: str, req_id: str) -> None:
    topic = f"analysis:{req_id}"
    if not symbol:
        connection.offer(_frame(topic, "error", {"detail": "symbol is required"}))
        return

    from backend.llm import use_model
    from backend.prefs import PrefsStore
    from backend.research.graph import ResearchAgent

    connection.offer(_frame(topic, "started", {"symbol": symbol}))
    try:
        prefs = await PrefsStore(db.db).get(connection.user_id)
        with use_model(prefs.get("omniroute_model")):
            report = await ResearchAgent().run(symbol)
        connection.offer(_frame(topic, "report", report.model_dump()))
    except Exception as exc:
        logger.warning("analysis of %s failed: %s", symbol, exc)
        connection.offer(_frame(topic, "error", {"detail": str(exc)}))
```

Update `_stream_chat`:

```python
async def _stream_chat(connection, message: str, history: list, req_id: str) -> None:
    topic = f"chat:{req_id}"
    if not message:
        connection.offer(_frame(topic, "error", {"detail": "message is required"}))
        return

    from backend.components.chat.agent import chat_agent
    from backend.llm import use_model
    from backend.prefs import PrefsStore

    try:
        prefs = await PrefsStore(db.db).get(connection.user_id)
        with use_model(prefs.get("omniroute_model")):
            async for event in chat_agent.stream_message(message, history):
                connection.offer(_frame(topic, event["type"], {"text": event["data"]}))
            connection.offer(_frame(topic, "done", {}))
    except Exception as exc:
        logger.warning("chat stream failed: %s", exc)
        connection.offer(_frame(topic, "error", {"detail": str(exc)}))
```

(`_stream_quick_analysis` is unchanged — no LLM call, out of scope per the spec's Non-goals.)

In `backend/suggestions/thesis.py`, update `attach_theses`:

```python
async def attach_theses(db, user_id: str, suggestions: list[dict], agent=None, limit: int = MAX_PER_SCAN) -> int:
    if not suggestions:
        return 0

    if agent is None:
        from backend.research.graph import ResearchAgent
        agent = ResearchAgent()

    from backend.llm import use_model
    from backend.prefs import PrefsStore
    prefs = await PrefsStore(db).get(user_id)

    store = SuggestionStore(db)
    attached = 0
    with use_model(prefs.get("omniroute_model")):
        for suggestion in suggestions[:limit]:
            thesis = await _thesis_for(agent, suggestion["symbol"])
            if thesis:
                await store.attach_thesis(user_id, suggestion["id"], thesis)
                attached += 1
    return attached
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_llm.py tests/test_thesis.py tests/test_ws_routes.py -v`
Expected: PASS (all new tests, and every pre-existing `test_ws_routes.py` test still passes with the fixture's added `db.db` mongomock attach).

Run the full suite, including confirming the modules the spec says must stay untouched really did:

Run: `cd backend && python -m pytest -v`
Expected: PASS. Additionally run `git diff --stat` before committing and confirm no changes appear under `backend/research/graph.py`, `backend/components/analyst/agent.py`, `backend/ai/analyst/sentiment.py` (or wherever `analyst/sentiment.py`/`analyst/events.py` actually live), `backend/master/search.py`, or `backend/instruments/resolve.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/llm.py backend/ws/routes.py backend/suggestions/thesis.py \
        backend/tests/test_llm.py backend/tests/test_thesis.py backend/tests/test_ws_routes.py
git commit -m "feat: per-user LLM model preference via a contextvars override (Phase 7)"
```

---

## Final verification (after all 7 tasks)

- [ ] Run the complete backend suite once more: `cd backend && python -m pytest -v` — must be 100% green.
- [ ] `docs/ROADMAP.md`: mark Phase 7 done, matching how Phase 6 was recorded (see the `docs: record Phase 6 ... as done` commit for the pattern) — one line for what landed, one line for what's explicitly deferred (no leader-elected pump, no sticky routing, no per-user model on the two dead legacy HTTP routes).
- [ ] Manually re-verify the spec's "Done when" list end-to-end is out of scope for this plan (it needs two real Uvicorn workers + real Redis on the VM, not something a unit test proves) — call this out to the user as a follow-up smoke test before actually flipping `--workers` to more than 1 in production, rather than assuming the merged code alone is sufficient.
