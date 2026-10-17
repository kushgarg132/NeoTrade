"""Picks (backend/forecast/): no look-ahead, charges, de-duplication,
walk-forward honesty, admin-only routes, store-before-outcome then score."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db as database
from backend.datalayer import bars
from backend.forecast import picks, setups, study


def _frames(days=420, n=25, seed=1):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2022-01-03", periods=days)
    frames = {}
    for i in range(n):
        close = 100 * np.exp(np.cumsum(rng.normal(0.0005 * (i % 5), 0.02, days)))
        open_ = close * (1 + rng.normal(0, 0.005, days))
        frames[f"S{i}"] = pd.DataFrame({
            "open": open_, "high": np.maximum(open_, close) * 1.01, "low": np.minimum(open_, close) * 0.99,
            "close": close, "volume": rng.uniform(1e5, 4e5, days),
        }, index=index)
    nifty = 20000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, days)))
    frames[bars.NIFTY] = pd.DataFrame({"open": nifty, "high": nifty, "low": nifty, "close": nifty,
                                       "volume": 0.0}, index=index)
    return frames


@pytest.mark.parametrize("setup", setups.SETUPS, ids=lambda s: s.name)
def test_a_signal_on_day_t_cannot_see_day_t_plus_one(setup):
    frames = _frames()
    full = setup.signals(setups.table(frames))
    assert full.notna().any().any(), "fixture must make the setup fire"
    for cut in (300, 350, 419):
        day = full.index[cut]
        truncated = setup.signals(setups.table({s: f.loc[:day] for s, f in frames.items()}))
        pd.testing.assert_frame_equal(truncated, full.loc[:day])


def test_momentum_vol_takes_the_top_decile_of_12_1_momentum_over_60_day_vol_on_month_starts():
    t = setups.table(_frames(n=40))
    close = t["close"]
    fires = setups.momentum_vol(t)
    score = (close.shift(21) / close.shift(252) - 1) / close.pct_change(fill_method=None).rolling(60).std()
    days = fires.index[fires.notna().any(axis=1)]
    assert len(days) >= 5 and all(d.month != fires.index[fires.index.get_loc(d) - 1].month for d in days)
    for day in days:
        assert set(fires.loc[day].dropna().index) == set(score.loc[day].nlargest(4).index)  # 40 names -> 4
    symbol = fires.loc[days[-1]].dropna().idxmax()
    text = setups.BY_NAME["momentum_vol_60"].explain(t, symbol, days[-1])
    assert text.startswith("12-month return skipping the last month") and "#1 of 40" in text


def test_entry_is_next_open_and_exit_is_close_after_horizon():
    t = setups.table(_frames())
    entry_day, exit_day, gross, net, nifty = study.outcome(t, "S0", 300, 20)
    assert entry_day == t["close"].index[301] and exit_day == t["close"].index[321]
    assert gross == pytest.approx(t["close"]["S0"].iat[321] / t["open"]["S0"].iat[301] - 1)
    assert nifty == pytest.approx(t["nifty_close"].iat[321] / t["nifty_open"].iat[301] - 1)
    assert study.outcome(t, "S0", 400, 20) is None  # not matured yet


def test_delivery_charges_on_a_flat_round_trip():
    # Rs 1L at Rs 100: buy 20 + STT 100 + exch 2.97 + SEBI 0.10 + stamp 15 + GST 4.15 = 142.22;
    # sell 20 + 100 + 2.97 + 0.10 + GST 4.15 + DP 15.93 = 143.15.
    assert study.net_return(100.0, 100.0) == pytest.approx(-(142.22 + 143.15) / 100_000)
    assert study.net_return(100.0, 110.0) == pytest.approx(0.10 - (142.22 + 153.51) / 100_000)  # sell side on Rs 1.1L


def test_signals_inside_an_open_event_window_are_dropped():
    fires = np.full(20, np.nan)
    fires[[0, 1, 5, 6, 7, 13]] = 1.0
    assert study.kept(fires, 5) == [0, 6, 13]


def _ev(signal, exit_, net, nifty=0.0):
    return (pd.Timestamp(signal), pd.Timestamp(exit_), net, nifty)


def test_walk_forward_predicts_only_from_events_matured_before_the_year():
    rows = [_ev("2020-03-01", "2020-04-01", 0.05)] * 30          # matured in 2020, all up
    rows += [_ev("2020-12-20", "2021-02-01", -0.05)] * 30        # signalled 2020, matures 2021: all down
    rows += [_ev("2021-05-01", "2021-06-01", -0.02, 0.01)] * 10
    ev = pd.DataFrame(rows, columns=["signal", "exit", "net", "nifty"])
    wf = study.walk_forward(ev)
    assert [y["year"] for y in wf["years"]] == [2021]  # 2020 has no matured past
    year = wf["years"][0]
    assert year["prior_n"] == 30 and year["predicted_p_up"] == 1.0  # the late-2020 losers are not used
    assert year["realised_p_up"] == 0.0 and wf["brier"] == 1.0
    assert wf["oos_excess"] == pytest.approx(-0.03) and wf["edge"] is False


# --- routes -----------------------------------------------------------------

def _user(role):
    return User(id="u1", google_sub="g", email="a@x.io", name="A", role=role,
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def mongo(monkeypatch):
    mongo = AsyncMongoMockClient()["test_db"]
    monkeypatch.setattr(database, "db", mongo)
    return mongo


def _client(role):
    from backend.routers import picks as picks_router

    app = FastAPI()
    app.include_router(picks_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    return TestClient(app)


@pytest.mark.parametrize("url", ["/api/v1/picks", "/api/v1/picks/history"])
def test_picks_are_admin_only(mongo, url):
    assert _client("user").get(url).status_code == 403
    assert _client("admin").get(url).status_code == 200


def test_payload_carries_the_survivorship_caveat(mongo):
    body = _client("admin").get("/api/v1/picks").json()
    assert body["picks"] == [] and body["forward"]["status"] == "unproven"
    assert any("Survivorship" in c for c in body["caveats"])


# --- the daily job ------------------------------------------------------------

def _fires_on_last_day(t):
    """S0 every 5th day (a past to measure) and on the table's last day."""
    out = pd.DataFrame(np.nan, index=t["close"].index, columns=t["close"].columns)
    out.iloc[::5, out.columns.get_loc("S0")] = 1.0
    out.iloc[-1, out.columns.get_loc("S0")] = 1.0
    return out


async def test_a_pick_is_stored_before_its_outcome_and_scored_later(monkeypatch):
    fake = setups.Setup("fake", "Fake", 2, _fires_on_last_day, lambda t, s, d: "fired")
    monkeypatch.setattr(setups, "SETUPS", (fake,))
    monkeypatch.setattr(study, "MIN_N", 1)
    db = AsyncMongoMockClient()["test_db"]
    frames = _frames(days=60, n=2)
    for symbol, df in frames.items():
        await bars.write(db, symbol, df.iloc[:56])
    day = frames["S0"].index[55]
    await picks.run(db, datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc))

    pick = await db[picks.PICKS].find_one({"_id": f"{day.date()}:fake:S0"})
    assert pick["outcome"] is None and pick["explanation"] == "fired"
    assert pick["entry_ref"] == pytest.approx(frames["S0"]["close"].iat[55])

    for symbol, df in frames.items():
        await bars.write(db, symbol, df)
    end = frames["S0"].index[-1]
    await picks.run(db, datetime(end.year, end.month, end.day, 12, tzinfo=timezone.utc))

    pick = await db[picks.PICKS].find_one({"_id": f"{day.date()}:fake:S0"})
    s0 = frames["S0"]
    assert pick["outcome"]["net"] == pytest.approx(study.net_return(s0["open"].iat[56], s0["close"].iat[58]))
    assert pick["outcome"]["exit_date"] == s0.index[58].date().isoformat()
    assert pick["entry_ref"] == pytest.approx(s0["close"].iat[55])  # what was stored is never rewritten


def test_forward_record_is_unproven_until_100_scored():
    scored = [{"p_up": 0.62, "outcome": {"won": i % 2 == 0, "beat_nifty": False}} for i in range(99)]
    assert picks.forward(scored)["status"] == "unproven"
    record = picks.forward(scored + scored[:1])
    assert record["status"] == "measured" and record["buckets"][0]["bucket"] == "60%–70%"
