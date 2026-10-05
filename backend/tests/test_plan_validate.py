import pytest

from backend.plan.validate import MAX_PLAN_POSITIONS, fallback_plan, validate

STRATS = {"orb_breakout", "gap_and_go"}


def _v(raw, trigger="pre_open", universe=("TCS",), nifty=("INFY", "TCS")):
    return validate(raw, trigger=trigger, strategies=STRATS, universe=set(universe), nifty200=set(nifty))


def test_clamps_only_tighten():
    assert _v({"risk_multiplier": 3.0, "max_positions": 50}).risk_multiplier == 1.0
    assert _v({"risk_multiplier": 3.0, "max_positions": 50}).max_positions == MAX_PLAN_POSITIONS
    assert _v({"risk_multiplier": 0.1}).risk_multiplier == 0.25


def test_drops_unknown_strategies_symbols_and_non_nifty_adds():
    plan = _v({"allow": [{"symbol": "tcs", "strategies": ["orb_breakout", "macd_crossover", "nope"]},
                         {"symbol": "ZZZ", "strategies": ["orb_breakout"]}],
               "add_symbols": ["INFY", "NOTNIFTY", "TCS"]})
    assert plan.allow == [{"symbol": "TCS", "strategies": ["orb_breakout"], "catalyst": None}]
    assert plan.add_symbols == ["INFY"]


def test_added_symbols_may_be_allowed_and_duplicates_merge():
    plan = _v({"add_symbols": ["INFY"], "allow": [
        {"symbol": "INFY", "strategies": ["gap_and_go"], "catalyst": {"item_id": "a", "direction": 0.7}},
        {"symbol": "INFY", "strategies": ["orb_breakout"]}]})
    assert plan.allow == [{"symbol": "INFY", "strategies": ["gap_and_go", "orb_breakout"],
                           "catalyst": {"item_id": "a", "direction": 0.7}}]


def test_json_wrapped_in_prose_is_parsed():
    assert _v('Here: {"skip_day": true, "rationale": ["CPI at 10"]} thanks').skip_day is True


def test_no_json_raises_value_error():
    with pytest.raises(ValueError):
        _v("no plan today")


def test_pre_open_plan_has_no_exits():
    assert _v({"exits": [{"symbol": "TCS", "reason": "x"}]}).exits == []


def test_rationale_is_trimmed():
    plan = _v({"rationale": ["x" * 500] + ["y"] * 9})
    assert len(plan.rationale) == 5 and len(plan.rationale[0]) == 200


def test_fallback_allows_everything_at_full_risk():
    plan = fallback_plan(STRATS, {"TCS", "INFY"}, "LLM down")
    assert plan.trigger == "fallback" and plan.risk_multiplier == 1.0 and plan.rationale == ["LLM down"]
    assert sorted(a["symbol"] for a in plan.allow) == ["INFY", "TCS"]
    assert all(sorted(a["strategies"]) == sorted(STRATS) for a in plan.allow)
