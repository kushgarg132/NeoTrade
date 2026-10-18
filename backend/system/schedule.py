"""The job clock times the UI quotes, read from the constants that drive the jobs."""

from datetime import time

from backend import scheduler
from backend.engine import autorun, session
from backend.guardrails import monitor


def _hm(t: time) -> str:
    return t.strftime("%H:%M")


def get() -> dict:
    """All times "HH:MM" IST; the frontend formats them."""
    return {
        "daily_pass": f"{scheduler.RUN_HOUR:02d}:{scheduler.RUN_MINUTE:02d}",
        "plan": _hm(autorun.PLAN_AT),
        "session_open": _hm(autorun.SESSION_OPEN),
        "session_close": _hm(autorun.SESSION_CLOSE),
        "square_off": f"{session.SQUARE_OFF_HOUR:02d}:{session.SQUARE_OFF_MINUTE:02d}",
        "morning": _hm(autorun.MORNING),
        "monitor_open": _hm(monitor.SESSION_OPEN),
        "monitor_close": _hm(monitor.SESSION_CLOSE),
        "exit_check_minutes": autorun.EXIT_CHECK_MINUTES,
    }
