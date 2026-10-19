"""NSE holiday calendar and the places that used to count a holiday as a session."""

import asyncio
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from mongomock_motor import AsyncMongoMockClient

from backend import scheduler
from backend.core import market_calendar as cal
from backend.datalayer import bars
from backend.engine import autorun
from backend.engine.session import IST
from backend.forecast import picks, setups, study
from backend.system import data_quality
from backend.tests.test_data_quality import _healthy, _picks_ran
from backend.tests.test_forecast_picks import _fires_on_last_day, _frames

DUSSEHRA = date(2026, 10, 20)  # Tuesday, an NSE holiday


def test_a_known_nse_holiday_is_not_a_trading_day_and_neighbours_skip_it():
    assert not cal.is_trading_day(DUSSEHRA)
    assert not cal.is_trading_day(date(2026, 10, 17)) and cal.is_trading_day(date(2026, 10, 19))
    assert cal.previous_trading_day(date(2026, 10, 21)) == date(2026, 10, 19)
    assert cal.next_trading_day(date(2026, 10, 19)) == date(2026, 10, 21)
    assert cal.last_trading_day(DUSSEHRA) == date(2026, 10, 19)
    assert cal.trading_days_between(date(2026, 10, 19), date(2026, 10, 22)) == [
        date(2026, 10, 19), date(2026, 10, 21), date(2026, 10, 22)]
    assert cal.add_trading_days(date(2026, 10, 16), 3) == date(2026, 10, 22)


def test_the_week_ends_on_the_last_trading_day():
    assert cal.is_last_trading_day_of_week(date(2026, 10, 16))
    assert not cal.is_last_trading_day_of_week(date(2026, 10, 15))
    assert cal.is_last_trading_day_of_week(date(2026, 4, 2))  # Good Friday 3-Apr is shut
    assert not cal.is_last_trading_day_of_week(date(2026, 4, 3))


def test_the_session_is_closed_on_a_holiday():
    assert not autorun.in_session(datetime(2026, 10, 20, 10, 0, tzinfo=IST))
    assert autorun.in_session(datetime(2026, 10, 21, 10, 0, tzinfo=IST))


async def test_data_quality_does_not_alert_on_a_holiday():
    holiday = datetime(2026, 10, 20, 11, 0, tzinfo=IST)
    db = AsyncMongoMockClient()["test_db"]
    await _picks_ran(db, datetime(2026, 10, 19, 10, 35, tzinfo=timezone.utc))  # Monday's, the last session
    redis = _healthy(**{"scheduler:last_pass": "2026-10-19"})
    assert data_quality.last_trading_day_at(holiday, data_quality.PASS_DONE) == date(2026, 10, 19)
    assert await data_quality.live(db, redis, holiday) == []
    redis.values.pop("scheduler:last_pass")
    assert await data_quality.alerts(db, redis, holiday) == []  # quiet like a weekend


async def test_a_pick_due_date_skips_the_holiday(monkeypatch):
    fake = setups.Setup("fake", "Fake", 2, _fires_on_last_day, lambda t, s, d: "fired")
    monkeypatch.setattr(setups, "SETUPS", (fake,))
    monkeypatch.setattr(study, "MIN_N", 1)
    db = AsyncMongoMockClient()["test_db"]
    for symbol, df in _frames(days=60, n=2).items():
        df.index = pd.bdate_range(end="2026-10-16", periods=60)
        await bars.write(db, symbol, df)
    await picks.run(db, datetime(2026, 10, 16, 12, tzinfo=timezone.utc))
    pick = await db[picks.PICKS].find_one({"_id": "2026-10-16:fake:S0"})
    assert pick["due_date"] == "2026-10-22"  # Mon, Wed (Tue is Dussehra), Thu: horizon 2 + 1


async def test_the_daily_pass_does_not_run_on_a_holiday(monkeypatch):
    runs = []
    days = iter([datetime(2026, 10, 20, 16, 0, tzinfo=IST), datetime(2026, 10, 21, 16, 0, tzinfo=IST)])

    async def run_locked(db, redis, pass_day=None):
        runs.append(1)

    class Clock(datetime):
        current = datetime(2026, 10, 20, 9, 0, tzinfo=IST)  # read before the first sleep

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current

    async def sleep(_):
        Clock.current = next(days)  # StopIteration after Wednesday ends the loop

    monkeypatch.setattr(scheduler, "_run_locked", run_locked)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    monkeypatch.setattr(scheduler, "seconds_until_next_run", lambda now: 0)
    monkeypatch.setattr(scheduler.asyncio, "sleep", sleep)
    try:
        await scheduler.scheduler_loop(None)
    except (StopIteration, RuntimeError):  # next() on a spent iterator inside a coroutine
        pass
    assert runs == [1]  # Tuesday skipped (the holiday), Wednesday ran


@pytest.mark.parametrize("at,phase", [
    (datetime(2026, 10, 19, 9, 14, tzinfo=IST), "pre"),
    (datetime(2026, 10, 19, 9, 15, tzinfo=IST), "session"),
    (datetime(2026, 10, 19, 15, 29, tzinfo=IST), "session"),
    (datetime(2026, 10, 19, 15, 30, tzinfo=IST), "post"),
    (datetime(2026, 10, 24, 11, 0, tzinfo=IST), "closed"),   # Saturday
    (datetime(2026, 10, 20, 10, 0, tzinfo=IST), "closed"),   # NSE holiday
])
def test_market_phase(at, phase):
    assert cal.market_phase(at) == phase


def test_next_open_skips_the_holiday():
    assert cal.next_open(datetime(2026, 10, 19, 16, 0, tzinfo=IST)) == datetime(2026, 10, 21, 9, 15, tzinfo=IST)
    assert cal.next_open(datetime(2026, 10, 19, 8, 0, tzinfo=IST)) == datetime(2026, 10, 19, 9, 15, tzinfo=IST)
