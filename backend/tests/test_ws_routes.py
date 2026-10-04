"""The /ws endpoint: authentication, origin, and the subscribe round trip.

A browser cannot set an Authorization header on a WebSocket handshake and
this app keeps its token in localStorage rather than a cookie, so the token
arrives as a query parameter -- which makes the handshake checks the only
thing standing between the socket and an unauthenticated client. CORS
middleware does not cover WebSocket handshakes either, hence the explicit
origin check.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.auth.models import User
from backend.ws import routes as ws_routes
from backend.ws.hub import Hub

_USER = User(
    id="alice", google_sub="sub-1", email="alice@example.com", name="Alice",
    picture=None, created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
)

ALLOWED_ORIGIN = "https://app.example.com"


@pytest.fixture
def hub(monkeypatch):
    fresh = Hub()
    monkeypatch.setattr(ws_routes, "hub", fresh)
    return fresh


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


def test_a_missing_token_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws") as socket:
            socket.receive_json()


def test_an_invalid_token_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws?token=nonsense") as socket:
            socket.receive_json()


def test_an_unknown_origin_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/v1/ws?token=good-token", headers={"origin": "https://evil.example.com"}
        ) as socket:
            socket.receive_json()


def test_a_valid_token_gets_a_ready_frame(client):
    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        ready = socket.receive_json()
        assert ready["event"] == "ready"
        assert ready["data"]["user_id"] == "alice"


def test_subscribing_then_receiving_a_published_event(client, hub):
    import asyncio

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()  # ready
        socket.send_json({"action": "subscribe", "topics": ["trades"]})
        assert socket.receive_json()["event"] == "subscribed"

        asyncio.run(hub.publish("alice", "trades", "opened", {"symbol": "RELIANCE"}))

        message = socket.receive_json()
        assert message["topic"] == "trades"
        assert message["data"]["symbol"] == "RELIANCE"


def test_a_socket_never_receives_another_users_events(client, hub):
    import asyncio

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "subscribe", "topics": ["trades"]})
        socket.receive_json()

        asyncio.run(hub.publish("bob", "trades", "opened", {"symbol": "TCS"}))
        asyncio.run(hub.publish("alice", "trades", "opened", {"symbol": "RELIANCE"}))

        message = socket.receive_json()
        assert message["data"]["symbol"] == "RELIANCE", "bob's event must never arrive here"


def test_a_disconnect_removes_the_connection_from_the_hub(client, hub):
    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "subscribe", "topics": ["prices:RELIANCE"]})
        socket.receive_json()

    assert hub.subscribed_symbols() == set()


def test_an_unknown_action_is_reported_not_fatal(client):
    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "teleport"})

        error = socket.receive_json()
        assert error["event"] == "error"

        socket.send_json({"action": "subscribe", "topics": ["pnl"]})
        assert socket.receive_json()["event"] == "subscribed", "socket stays usable"


# ---------------------------------------------------------------------------
# Streamed analysis and chat, which replace the old SSE endpoints
# ---------------------------------------------------------------------------

def test_analysis_streams_back_on_its_own_topic(client, monkeypatch):
    class _Report:
        def model_dump(self):
            return {"symbol": "RELIANCE", "thesis": "Fine business."}

    class _Agent:
        async def run(self, symbol):
            return _Report()

    monkeypatch.setattr("backend.research.graph.ResearchAgent", lambda: _Agent())

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "analyze", "symbol": "RELIANCE", "req_id": "r1"})

        started = socket.receive_json()
        assert started == {**started, "topic": "analysis:r1", "event": "started"}
        report = socket.receive_json()
        assert report["event"] == "report"
        assert report["data"]["thesis"] == "Fine business."


def test_quick_analysis_streams_back_on_its_own_topic(client, monkeypatch):
    class _Snapshot:
        def model_dump(self, mode="python"):
            return {"symbol": "RELIANCE", "company_info": {"symbol": "RELIANCE"}}

    monkeypatch.setattr("backend.research.quick.quick_analysis", AsyncMock(return_value=_Snapshot()))

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "quick_analyze", "symbol": "RELIANCE", "req_id": "q1"})

        report = socket.receive_json()
        assert report == {**report, "topic": "quick_analysis:q1", "event": "report"}
        assert report["data"]["symbol"] == "RELIANCE"


def test_a_quick_analysis_failure_is_reported_on_the_topic(client, monkeypatch):
    monkeypatch.setattr(
        "backend.research.quick.quick_analysis", AsyncMock(side_effect=RuntimeError("provider down"))
    )

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "quick_analyze", "symbol": "RELIANCE", "req_id": "q2"})

        failure = socket.receive_json()
        assert failure["topic"] == "quick_analysis:q2"
        assert failure["event"] == "error"
        assert "provider down" in failure["data"]["detail"]


def test_chat_streams_thinking_then_content_then_done(client, monkeypatch):
    async def fake_stream(db, redis, user_id, message, history, context):
        yield {"type": "thinking", "data": "looking it up"}
        yield {"type": "content", "data": "Reliance is a conglomerate."}
        yield {"type": "action", "data": {"id": "a1", "summary": "Approve SJVN"}}

    monkeypatch.setattr("backend.chat.agent.stream_chat", fake_stream)

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "chat", "message": "what is reliance", "req_id": "c1"})

        events = [socket.receive_json() for _ in range(4)]

    assert [e["event"] for e in events] == ["thinking", "content", "action", "done"]
    assert all(e["topic"] == "chat:c1" for e in events)
    assert events[1]["data"] == {"text": "Reliance is a conglomerate."}
    assert events[2]["data"] == {"id": "a1", "summary": "Approve SJVN"}


def test_an_analysis_failure_is_reported_on_the_topic(client, monkeypatch):
    class _Agent:
        async def run(self, symbol):
            raise RuntimeError("provider down")

    monkeypatch.setattr("backend.research.graph.ResearchAgent", lambda: _Agent())

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "analyze", "symbol": "RELIANCE", "req_id": "r2"})
        socket.receive_json()  # started

        failure = socket.receive_json()
        assert failure["event"] == "error"
        assert "provider down" in failure["data"]["detail"]


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

    async def fake_stream(db, redis, user_id, message, history, context):
        from backend.llm import _model_override
        seen_model["model"] = _model_override.get()
        seen_model["user_id"], seen_model["context"] = user_id, context
        yield {"type": "content", "data": "hi"}

    monkeypatch.setattr("backend.chat.agent.stream_chat", fake_stream)

    with client.websocket_connect(
        "/api/v1/ws?token=good-token", headers={"origin": ALLOWED_ORIGIN}
    ) as socket:
        socket.receive_json()
        socket.send_json({"action": "chat", "message": "hi", "req_id": "c2", "context": {"page": "/portfolio"}})
        socket.receive_json()  # content
        socket.receive_json()  # done

    assert seen_model["model"] == "user/preferred"
    assert seen_model["user_id"] == "alice" and seen_model["context"] == {"page": "/portfolio"}
