"""GET /system/schedule returns the constants the jobs actually use."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import scheduler
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.engine import autorun, session
from backend.guardrails import monitor
from backend.system import router as system_router


def test_schedule_matches_job_constants():
    app = FastAPI()
    app.include_router(system_router.router)
    app.dependency_overrides[get_current_user] = lambda: User(
        id="a", google_sub="g", email="a@x.io", name="A", role="user",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    body = TestClient(app).get("/system/schedule").json()
    assert body == {
        "daily_pass": f"{scheduler.RUN_HOUR:02d}:{scheduler.RUN_MINUTE:02d}",
        "plan": autorun.PLAN_AT.strftime("%H:%M"),
        "session_open": autorun.SESSION_OPEN.strftime("%H:%M"),
        "session_close": autorun.SESSION_CLOSE.strftime("%H:%M"),
        "square_off": f"{session.SQUARE_OFF_HOUR:02d}:{session.SQUARE_OFF_MINUTE:02d}",
        "morning": autorun.MORNING.strftime("%H:%M"),
        "monitor_open": monitor.SESSION_OPEN.strftime("%H:%M"),
        "monitor_close": monitor.SESSION_CLOSE.strftime("%H:%M"),
        "exit_check_minutes": autorun.EXIT_CHECK_MINUTES,
    }
