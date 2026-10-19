from datetime import datetime, timedelta

import pytest

from backend.portfolio import digest
from backend.routers.settings import IST
from backend.tests.test_settings_router import _client, db  # noqa: F401


def _by(days):
    return (datetime.now(IST).date() + timedelta(days=days)).isoformat()


@pytest.fixture
def client(db, monkeypatch):  # noqa: F811
    async def pulse(*_a, **_k):
        return {"value": 500000.0}

    monkeypatch.setattr(digest, "pulse", pulse)
    return _client(db)


def _put(client, **goal):
    return client.put("/api/v1/settings/preferences", json={"goal": goal})


def test_goal_saved_with_server_start(client):
    r = _put(client, kind="value", target=1000000, by=_by(365))
    assert r.status_code == 200
    g = r.json()["goal"]
    assert g["by"] == _by(365) and g["start_value"] == 500000.0
    assert g["start"] == datetime.now(IST).date().isoformat()


def test_edit_keeps_original_start(client, db):  # noqa: F811
    _put(client, kind="value", target=1000000, by=_by(365))
    import asyncio

    asyncio.run(db["user_prefs"].update_one({"user_id": "alice"}, {"$set": {"goal.start": "2026-01-01"}}))
    g = _put(client, kind="value", target=2000000, by=_by(400)).json()["goal"]
    assert g["start"] == "2026-01-01" and g["target"] == 2000000


@pytest.mark.parametrize("goal", [
    dict(kind="value", target=0, by="+30"),
    dict(kind="value", target=-5, by="+30"),
    dict(kind="value", target=100, by="past"),
    dict(kind="value", target=100, by="today"),
    dict(kind="bogus", target=100, by="+30"),
])
def test_invalid_goal_422(client, goal):
    goal["by"] = {"+30": _by(30), "past": _by(-1), "today": _by(0)}[goal["by"]]
    assert _put(client, **goal).status_code == 422


def test_goal_can_be_removed(client):
    assert _put(client, kind="value", target=1000000, by=_by(365)).status_code == 200
    r = client.delete("/api/v1/settings/goal")
    assert r.status_code == 200 and r.json().get("goal") is None
    assert client.get("/api/v1/settings/preferences").json().get("goal") is None
