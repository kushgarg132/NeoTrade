"""The single live socket: /api/v1/ws.

One connection carries every stream the app needs -- prices, trades,
positions, P&L, runs, suggestions, and streamed analysis -- selected by
topic subscription, so a page opens one socket rather than one per widget.

Two things differ from the HTTP routes and both are deliberate:

* The token arrives as a query parameter. Browsers cannot set an
  Authorization header on a WebSocket handshake, and this app keeps its
  session token in localStorage rather than a cookie, so there is nowhere
  else for it to travel. It is validated with the same primitives the HTTP
  dependency uses.
* The origin is checked here by hand. Starlette's CORS middleware does not
  apply to WebSocket handshakes, so without this any page anywhere could
  open an authenticated socket.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.auth.jwt import InvalidSessionToken, decode_session_jwt
from backend.auth.models import User
from backend.auth.store import UserStore
from backend.configs.settings import settings
from backend.database import db
from backend.ws.hub import hub

logger = logging.getLogger(__name__)

router = APIRouter()

CLOSE_UNAUTHORIZED = 1008
PING_SECONDS = 20


async def authenticate_token(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    try:
        user_id = decode_session_jwt(token)
    except InvalidSessionToken:
        return None
    return await UserStore(db.db).get_by_id(user_id)


def origin_allowed(origin: Optional[str]) -> bool:
    # A non-browser client (curl, a test, the deploy smoke check) sends no
    # Origin at all; there is no cross-site risk to protect it from.
    if origin is None:
        return True
    allowed = settings.CORS_ALLOWED_ORIGINS
    return "*" in allowed or origin in allowed


@router.websocket("/ws")
async def stream(websocket: WebSocket, token: Optional[str] = Query(default=None)):
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    user = await authenticate_token(token)
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    await websocket.accept()
    connection = hub.connect(user.id)
    await websocket.send_json({"topic": "system", "event": "ready", "data": {"user_id": user.id}})

    pump = asyncio.create_task(_pump(websocket, connection))
    try:
        while True:
            message = await websocket.receive_json()
            await _handle(websocket, connection, message)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.info("socket for %s closing: %s", user.id, exc)
    finally:
        pump.cancel()
        hub.disconnect(connection)


async def _pump(websocket: WebSocket, connection) -> None:
    """Forwards hub events to the browser, with a periodic ping so an idle
    socket doesn't get culled by a proxy."""
    while True:
        try:
            message = await asyncio.wait_for(connection.queue.get(), timeout=PING_SECONDS)
        except asyncio.TimeoutError:
            message = {"topic": "system", "event": "ping", "data": {}}
        await websocket.send_json(message)


async def _handle(websocket: WebSocket, connection, message: dict) -> None:
    action = message.get("action")
    topics = message.get("topics") or []

    if action == "analyze":
        asyncio.create_task(_stream_analysis(connection, message.get("symbol", ""), message.get("req_id", "")))
    elif action == "quick_analyze":
        asyncio.create_task(_stream_quick_analysis(connection, message.get("symbol", ""), message.get("req_id", "")))
    elif action == "chat":
        asyncio.create_task(_stream_chat(
            connection, message.get("message", ""), message.get("history") or [], message.get("req_id", ""),
            message.get("context") or {},
        ))
    elif action == "subscribe":
        connection.subscribe(topics)
        await websocket.send_json({"topic": "system", "event": "subscribed", "data": {"topics": sorted(connection.topics)}})
    elif action == "unsubscribe":
        connection.unsubscribe(topics)
        await websocket.send_json({"topic": "system", "event": "unsubscribed", "data": {"topics": sorted(connection.topics)}})
    elif action == "ping":
        await websocket.send_json({"topic": "system", "event": "pong", "data": {}})
    else:
        await websocket.send_json({
            "topic": "system", "event": "error", "data": {"detail": f"Unknown action {action!r}"},
        })


# ---------------------------------------------------------------------------
# Streaming work. These write into the connection's own queue rather than the
# socket: the pump task is the only writer to the WebSocket itself, so two
# concurrent streams can't interleave halfway through a frame.
# ---------------------------------------------------------------------------

def _frame(topic: str, event: str, data) -> dict:
    return {
        "topic": topic,
        "event": event,
        "data": data,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


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


async def _stream_quick_analysis(connection, symbol: str, req_id: str) -> None:
    """The non-AI half of a stock enquiry: quote, fundamentals, price-based
    technicals. No LLM call, so this is what renders while (or instead of)
    the separate `analyze` action's AI report."""
    topic = f"quick_analysis:{req_id}"
    if not symbol:
        connection.offer(_frame(topic, "error", {"detail": "symbol is required"}))
        return

    from backend.research.quick import quick_analysis

    try:
        snapshot = await quick_analysis(symbol)
        connection.offer(_frame(topic, "report", snapshot.model_dump()))
    except Exception as exc:
        logger.warning("quick analysis of %s failed: %s", symbol, exc)
        connection.offer(_frame(topic, "error", {"detail": str(exc)}))


async def _stream_chat(connection, message: str, history: list, req_id: str, context: dict | None = None) -> None:
    topic = f"chat:{req_id}"
    if not message:
        connection.offer(_frame(topic, "error", {"detail": "message is required"}))
        return

    from backend.chat import agent
    from backend.llm import use_model
    from backend.prefs import PrefsStore

    try:
        prefs = await PrefsStore(db.db).get(connection.user_id)
        with use_model(prefs.get("omniroute_model")):
            async for event in agent.stream_chat(db.db, db.redis, connection.user_id, message, history, context or {}):
                if event["type"] in ("step", "answer_end"):  # Telegram-only signals
                    continue
                data = event["data"] if event["type"] in ("action", "suggestions") else {"text": event["data"]}
                connection.offer(_frame(topic, event["type"], data))
            connection.offer(_frame(topic, "done", {}))
    except Exception as exc:
        logger.warning("chat stream failed: %s", exc)
        connection.offer(_frame(topic, "error", {"detail": str(exc)}))
