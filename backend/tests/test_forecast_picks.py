"""Picks (backend/forecast/): no look-ahead, charges, de-duplication,
walk-forward honesty, admin-only routes, store-before-outcome then score."""

import asyncio
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
from backend.lab.assumptions import Execution, round_trip_return


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
    flat = Execution(slippage_bps=0.0)
    assert round_trip_return(100.0, 100.0, flat) == pytest.approx(-(142.22 + 143.15) / 100_000)
    assert round_trip_return(100.0, 110.0, flat) == pytest.approx(0.10 - (142.22 + 153.51) / 100_000)  # sell side on Rs 1.1L
    # study returns now include 10 bps adverse slippage per side
    assert study.net_return(100.0, 100.0) == pytest.approx(-0.004849702)
    assert study.net_return(100.0, 110.0) == pytest.approx(0.094847098)


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


def test_factor_closes_cache_file_name_is_stable_across_processes(tmp_path, monkeypatch):
    import pandas as pd
    from backend.factor import data
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(data, "_download", lambda tickers, start: pd.DataFrame(
        {t: [1.0] for t in tickers}, index=pd.to_datetime(["2020-01-01"])))
    data.closes(["B", "A"])
    # sha1("A,B")[:16], independent of PYTHONHASHSEED
    assert [p.name for p in tmp_path.iterdir()] == ["closes-2008-01-01-a1f86715f2bfd6bb.pkl"]


def test_factor_report_saves_the_keys_the_gate_reads(monkeypatch):
    import asyncio
    from mongomock_motor import AsyncMongoMockClient
    from backend import database
    from backend.factor import report
    from backend.risk.backtest_gate import BacktestGateStore
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(database.db, "connect_to_database", lambda: asyncio.sleep(0))
    monkeypatch.setattr(database.db, "db", db, raising=False)
    asyncio.run(report._save({"verdict": {"passed": True}}))
    assert asyncio.run(BacktestGateStore(db).live_eligible(report.STRATEGY_NAME)) is True


# --- the served list ------------------------------------------------------------

from datetime import date  # noqa: E402

GRADES = {"momentum": "A", "pullback": "B", "breakout": "C"}


def _p(day, symbol="A", excess=0.02, beat=0.6, entry=100.0, due="2026-10-30", label="Momentum", setup="momentum"):
    return {"_id": f"{day}:{setup}:{symbol}", "date": day, "symbol": symbol, "setup": setup, "label": label,
            "median_excess": excess, "p_beat_nifty": beat, "entry_ref": entry, "due_date": due}


TODAY = date(2026, 10, 21)  # Wed


def test_setups_are_graded_from_the_adjusted_edge():
    study_doc = {"setups": [
        {"setup": "momentum", "adjusted": {"excess": 0.007, "t": 2.2, "edge": True}},
        {"setup": "pullback", "adjusted": {"excess": 0.004, "t": 1.1, "edge": False}},
        {"setup": "momentum_vol_60", "adjusted": {"excess": 0.004, "t": 0.4, "edge": False}},
        {"setup": "low_vol", "adjusted": {"excess": -0.02, "t": -2.3, "edge": False}},
        {"setup": "fresh"}]}
    assert picks.setup_grades(study_doc) == {"momentum": "A", "pullback": "B", "momentum_vol_60": "C", "low_vol": "C", "fresh": "C"}


def test_every_grade_is_served_a_first_and_a_low_beat_rate_is_a_label_not_a_filter():
    """2026-10-23: only pullback fired, it had no edge, and Ideas sat empty."""
    out = picks.serve([_p("2026-10-21", "P", setup="pullback", label="Pullback in uptrend"),
                       _p("2026-10-21", "X", setup="breakout"), _p("2026-10-21", "L", beat=0.5)], [], {}, TODAY, GRADES)
    assert [(p["symbol"], p["grade"]) for p in out["shown"]] == [("L", "A"), ("P", "B"), ("X", "C")]
    assert out["shown"][0]["beats_nifty_odds"] is False and out["shown"][1]["beats_nifty_odds"] is True
    assert out["hidden_count"] == 0 and out["grade_text"]["A"].startswith("Proven")


def test_an_earlier_pick_stays_until_due_and_a_big_move_is_flagged_not_hidden():
    t = [_p("2026-10-21", "T")]
    older = [_p("2026-10-01", "MONTH", due="2026-12-24"),  # a month-start 60-day pick, weeks later
             _p("2026-10-19", "DUE", due="2026-10-21"), _p("2026-10-19", "FAR"), _p("2026-10-16", "OK")]
    prices = {"MONTH": 101.0, "DUE": 100, "FAR": 105, "OK": 101.9}
    out = picks.serve(t, older, prices, TODAY, GRADES)
    by = {p["symbol"]: p for p in out["shown"]}
    assert set(by) == {"T", "OK", "MONTH"} and out["hidden_count"] == 1  # DUE is past due; FAR is the 4th A
    assert by["OK"]["fired_on"] == "2026-10-16" and by["OK"]["days_since"] == 2 and by["OK"]["days_left"] == 7
    assert by["OK"]["price_now"] == 101.9 and by["OK"]["move_since_entry"] == pytest.approx(0.019)
    assert by["OK"]["missed_entry"] is False
    far = picks.serve([], [_p("2026-10-19", "FAR")], {"FAR": 105}, TODAY, GRADES)["shown"][0]
    assert far["missed_entry"] is True and far["move_since_entry"] == pytest.approx(0.05)


def test_the_same_setup_and_symbol_on_several_days_shows_once_newest_first():
    out = picks.serve([_p("2026-10-21", "R", setup="pullback")],
                      [_p("2026-10-19", "R", setup="pullback"), _p("2026-10-16", "R", setup="pullback"),
                       _p("2026-10-16", "S", setup="pullback"), _p("2026-10-15", "S", setup="pullback")],
                      {"S": 100.0}, TODAY, GRADES)
    assert [(p["symbol"], p["fired_on"]) for p in out["shown"]] == [("R", "2026-10-21"), ("S", "2026-10-16")]


def test_in_zone_first_then_ranked_by_excess_and_capped_at_three_per_grade():
    ps = [_p("2026-10-21", "A", 0.01, 0.9), _p("2026-10-21", "B", 0.03, 0.6), _p("2026-10-21", "C", 0.03, 0.7),
          _p("2026-10-21", "D", 0.02, 0.6)]
    missed = _p("2026-10-19", "M", 0.09, 0.9)
    out = picks.serve(ps, [missed], {"M": 110.0}, TODAY, GRADES)
    assert [p["symbol"] for p in out["shown"]] == ["C", "B", "D"]
    assert out["hidden_count"] == 2 and out["hidden_reason"] == "2 more grade A hidden: top 3 per grade"


def test_experimental_setup_is_flagged():
    out = picks.serve([_p("2026-10-21", "R", setup="rs_leaders_regime"), _p("2026-10-21", "M")], [], {},
                      TODAY, {"rs_leaders_regime": "A", "momentum": "A"})
    assert {p["symbol"]: p["experimental"] for p in out["shown"]} == {"R": True, "M": False}


def test_payload_has_shown_and_keeps_picks(mongo):
    asyncio.run(mongo.picks.insert_one({**_p("2026-10-21", "X", 0.0, 0.5), "strength": 1.0}))
    asyncio.run(mongo.picks_study.insert_one({"_id": "latest", "setups": [{"setup": "momentum", "adjusted": {"edge": False}}]}))
    body = _client("admin").get("/api/v1/picks").json()
    assert [p["symbol"] for p in body["picks"]] == ["X"]
    assert [(p["symbol"], p["grade"]) for p in body["shown"]] == [("X", "C")] and body["grades"] == {"momentum": "C"}


# --- the adjusted edge ------------------------------------------------------------

def _events(excess_by_month):
    rows = []
    for i, ex in enumerate(excess_by_month):
        for k in range(3):
            rows.append((pd.Timestamp(2022 + i // 12, i % 12 + 1, 3), 0.01 * k + ex, 0.0))
    return pd.DataFrame(rows, columns=["signal", "net", "nifty"])


def test_adjusted_edge_subtracts_the_same_month_universe_baseline():
    rng = np.random.default_rng(3)
    ex = 0.05 + rng.normal(0, 0.01, 24)
    ev = _events(ex)
    months = pd.period_range("2022-01", periods=24, freq="M")
    wf = {"years": [{"year": 2022}, {"year": 2023}]}
    on_baseline = study.adjusted_edge(ev, pd.Series(0.05 + 0.01, index=months), wf)  # the average stock earned as much
    assert on_baseline["excess"] < 0 and on_baseline["edge"] is False
    beats = study.adjusted_edge(ev, pd.Series(0.0, index=months), wf)
    assert beats["excess"] > 0.05 and beats["t"] >= study.ADJ_MIN_T and beats["edge"] is True
    assert study.adjusted_edge(ev, pd.Series(0.0, index=months), {"years": []})["edge"] is False


# --- price levels ------------------------------------------------------------------

def test_levels_take_the_tighter_stop_and_the_stocks_own_range():
    p = {"entry_ref": 100.0, "atr": 2.0, "expected": {"median": 0.04, "p10": -0.08, "p90": 0.12,
                                                      "range_stock": {"p10": -0.06, "p90": 0.15}}}
    lv = picks.levels(p)
    assert lv["entry_zone"] == [100.0, 103.0]
    assert lv["target"] == 104.0 and lv["stretch"] == 115.0
    assert lv["stop"] == 96.0  # 2 ATR (96) is tighter than the stock's p10 (94)
    assert lv["reward_risk"] == 1.0


def test_levels_never_put_a_stop_above_entry_or_a_target_below_it():
    lv = picks.levels({"entry_ref": 100.0, "expected": {"median": -0.001, "p10": 0.01, "p90": 0.05}})
    assert lv["stop"] is None and lv["target"] is None and lv["reward_risk"] is None and lv["stretch"] == 105.0
    assert picks.levels({"entry_ref": 100.0, "expected": {}}) is None


def test_atr_is_the_mean_true_range():
    import pandas as pd
    idx = pd.bdate_range("2026-10-01", periods=16)
    close = pd.DataFrame({"S": [100.0] * 16}, index=idx)
    t = {"close": close, "high": close + 1, "low": close - 1}
    assert picks._atr(t, "S", 15) == pytest.approx(2.0)
    assert picks._atr({"close": close, "high": close, "low": close}, "S", 15) is None


def test_served_picks_carry_levels():
    out = picks.serve([{**_p("2026-10-21", "A"), "expected": {"median": 0.05, "p10": -0.05, "p90": 0.1}}], [], {}, TODAY, GRADES)
    assert out["shown"][0]["levels"]["target"] == 105.0
