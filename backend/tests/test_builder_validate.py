import copy

import pytest

from backend.builder.validate import describe, slugify, validate_spec
from backend.strategies.built import load_ok

EXAMPLE = {
    "setup": {"gap": {"direction": "down", "min_pct": 1.0}},
    "filters": {"price_vs_vwap": {"side": "above"}, "volume_confirm": {"multiple": 2.0},
                "time_window": {"start": "09:30", "end": "14:45"}},
    "side": "long",
    "stop": {"atr_multiple": 1.0},
    "target": {"r_multiple": 2.0},
}


def _ex(**kw):
    s = copy.deepcopy(EXAMPLE)
    s.update(kw)
    return s


def test_example_roundtrips_and_loads():
    clean, why = validate_spec(EXAMPLE, [])
    assert why == "" and load_ok(clean) and clean == EXAMPLE
    assert validate_spec(clean, [])[0] == clean  # idempotent


def test_clamps_and_snaps():
    c, _ = validate_spec(_ex(setup={"gap": {"direction": "down", "min_pct": 9}}), [])
    assert c["setup"]["gap"]["min_pct"] == 4.0
    c, _ = validate_spec(_ex(setup={"gap": {"direction": "down", "min_pct": 1.1}}), [])
    assert c["setup"]["gap"]["min_pct"] == 1.0
    c, _ = validate_spec(_ex(setup={"rsi_cross": {"period": 13.4, "level": 33, "direction": "up"}}), [])
    assert c["setup"]["rsi_cross"] == {"period": 13, "level": 35, "direction": "up"}
    assert isinstance(c["setup"]["rsi_cross"]["period"], int)


def test_unknown_block_dropped_and_no_stop_refused():
    c, _ = validate_spec(_ex(filters={**EXAMPLE["filters"], "magic": {"x": 1}}), [])
    assert "magic" not in c["filters"]
    raw = _ex()
    del raw["stop"]
    assert validate_spec(raw, []) == (None, "no stop")


def test_stop_needs_exactly_one():
    both = _ex(stop={"atr_multiple": 1, "setup_bar": True})
    assert validate_spec(both, []) == (None, "stop needs one of atr_multiple or setup_bar")
    c, _ = validate_spec(_ex(stop={"setup_bar": {}}), [])
    assert c["stop"] == {"setup_bar": True} and load_ok(c)


def test_two_setups_refused():
    raw = _ex(setup={"gap": {"direction": "up", "min_pct": 1}, "volume_spike": {"multiple": 2}})
    assert validate_spec(raw, []) == (None, "exactly one setup")


def test_missing_required_param_refuses_setup_and_drops_filter():
    assert validate_spec(_ex(setup={"gap": {"direction": "up"}}), [])[0] is None
    c, _ = validate_spec(_ex(filters={"volume_confirm": {}, "price_vs_vwap": {"side": "sideways"}}), [])
    assert c["filters"] == {}


def test_shorthand_and_exits_key():
    raw = _ex(filters={"price_vs_vwap": "below", "regime_is": ["risk_on", "risk_on", "bogus"]})
    stop, target = raw.pop("stop"), raw.pop("target")
    raw["exits"] = {"stop": stop, "target": target, "time_stop": {"minutes": 100}}
    c, why = validate_spec(raw, [])
    assert why == "" and c["filters"] == {"price_vs_vwap": {"side": "below"}, "regime_is": {"regimes": ["risk_on"]}}
    assert "time_stop" not in c and load_ok(c)  # dropped like any unknown key (R16)
    c, _ = validate_spec(_ex(filters={"regime_is": ["bogus"]}), [])
    assert c["filters"] == {}


def test_time_window_and_atr_pct():
    c, _ = validate_spec(_ex(filters={"time_window": {"start": "09:00", "end": "15:30"}}), [])
    assert c["filters"]["time_window"] == {"start": "09:20", "end": "14:45"}
    c, _ = validate_spec(_ex(filters={"time_window": {"start": "09:32", "end": "10:00"}}), [])
    assert c["filters"]["time_window"]["start"] == "09:30"
    c, _ = validate_spec(_ex(filters={"time_window": {"start": "11:00", "end": "10:00"}}), [])
    assert c["filters"] == {}
    c, _ = validate_spec(_ex(filters={"atr_pct": {"min": 2.0, "max": 1.0}}), [])
    assert c["filters"] == {}
    c, _ = validate_spec(_ex(filters={"atr_pct": {"min": 0.5, "max": 2.0}}), [])
    assert c["filters"]["atr_pct"] == {"min": 0.5, "max": 2.0}


def test_at_most_three_filters_first_kept():
    f = {"price_vs_vwap": {"side": "above"}, "volume_confirm": {"multiple": 2}, "sector_rs": {"min": 0},
         "atr_pct": {"min": 0.5, "max": 2}}
    c, _ = validate_spec(_ex(filters=f), [])
    assert list(c["filters"]) == ["price_vs_vwap", "volume_confirm", "sector_rs"]


def test_bad_side_and_target():
    assert validate_spec(_ex(side="sideways"), [])[0] is None
    raw = _ex()
    del raw["target"]
    assert validate_spec(raw, []) == (None, "no target")


def test_duplicate_within_the_same_batch_is_refused():
    a, _ = validate_spec(EXAMPLE, [])
    near = _ex(setup={"gap": {"direction": "down", "min_pct": 1.25}})
    b, why = validate_spec(near, [{"slug": "a", "spec": a}])
    assert b is None and why == "duplicate of a"
    far = _ex(setup={"gap": {"direction": "down", "min_pct": 2.0}})
    assert validate_spec(far, [{"slug": "a", "spec": a}])[0] is not None
    other_side = _ex(side="short")
    assert validate_spec(other_side, [{"slug": "a", "spec": a}])[0] is not None


def test_describe_reads_the_example():
    assert describe(EXAMPLE) == ("Long when the stock gapped down at least 1% and is above VWAP on 2× volume, "
                                 "9:30 AM–2:45 PM; stop 1× ATR, target 2R.")


def test_slugify():
    s = slugify(EXAMPLE)
    assert s == "gap-down-vwap-above-long" and len(s) <= 40


def test_every_validated_spec_loads():
    for setup in ({"orb_break": {"range_minutes": 12}}, {"vwap_cross": {"mode": "lose"}},
                  {"ema_pullback": {"period": 20}}, {"volume_spike": {"multiple": 3}}):
        for stop in ({"atr_multiple": 9}, {"setup_bar": True}):
            c, why = validate_spec(_ex(setup=setup, stop=stop, target={"r_multiple": 0}), [])
            assert c is not None, why
            assert load_ok(c) and describe(c) and len(slugify(c)) <= 40


def _deep(n=5000):
    x = []
    for _ in range(n):
        x = [x]
    return x


HOSTILE = [float("nan"), float("inf"), float("-inf"), 10**400, None, "x", [], {}, True, list(range(10_000)), _deep()]


def _places(v):
    base = _ex()
    yield v
    yield [v]
    for k in ("setup", "filters", "side", "stop", "target", "time_stop", "exits"):
        yield {**base, k: v}
    yield {**base, "exits": {"stop": v, "target": v, "time_stop": v}}
    yield {**base, "setup": {"gap": {"direction": v, "min_pct": v}}}
    yield {**base, "setup": {"gap": v}}
    for f, params in EXAMPLE["filters"].items():
        yield {**base, "filters": {f: v}}
        yield {**base, "filters": {f: {k: v for k in params}}}
    yield {**base, "filters": {"regime_is": {"regimes": [v]}, "atr_pct": {"min": 1, "max": v}}}
    for k in ("stop", "target", "time_stop"):
        yield {**base, k: {"atr_multiple": v, "setup_bar": v, "r_multiple": v, "minutes": v}}


@pytest.mark.parametrize("v", range(len(HOSTILE)))
def test_hostile_values_never_raise(v):
    for raw in _places(HOSTILE[v]):
        out = validate_spec(raw, [{"slug": "a", "spec": HOSTILE[v]}, HOSTILE[v]])
        assert isinstance(out, tuple) and len(out) == 2
        if out[0] is not None:
            assert load_ok(out[0])


def test_time_stop_is_dropped_silently():
    c, why = validate_spec(_ex(time_stop={"minutes": 30}), [])
    assert why == "" and "time_stop" not in c and load_ok(c)
    assert "exit after" not in describe(c)


SWING = {
    "horizon": "swing",
    "setup": {"breakout_n": {"days": 20}},
    "filters": {"trend_ma": {"period": "200"}, "liquidity": {"min_cr": 5}},
    "side": "long",
    "stop": {"atr_multiple": 2.0},
    "target": {"r_multiple": 3.0},
    "max_hold_days": {"days": 15},
    "trail_atr": {"multiple": 3.0},
}


def _sw(**kw):
    s = copy.deepcopy(SWING)
    s.update(kw)
    return s


def test_swing_spec_validates_and_describes():
    clean, why = validate_spec(SWING, [])
    assert why == "" and clean == SWING and load_ok(clean)  # a validated swing spec loads
    assert validate_spec(clean, [])[0] == clean
    assert describe(clean) == ("Swing, long: close above the 20-day high, above the 200-day average, "
                               "turnover of at least ₹5 crore a day; stop 2× ATR, target 3R, "
                               "trailing 3× ATR, out after 15 days.")
    assert slugify(clean).startswith("swing-") and len(slugify(clean)) <= 40
    c, _ = validate_spec(_sw(stop={"swing_low": True}, trail_atr=None,
                             setup={"pullback_ma": {"trend": "50", "pull": "20"}}), [])
    assert c["stop"] == {"swing_low": True} and "trail_atr" not in c and load_ok(c)
    assert "stop below the 5-day low" in describe(c) and "trailing" not in describe(c)
    # clamp and snap, choice values must be members
    c, _ = validate_spec(_sw(max_hold_days={"days": 99}, setup={"breakout_n": {"days": 22}}), [])
    assert c["max_hold_days"] == {"days": 40} and c["setup"]["breakout_n"]["days"] == 20
    c, _ = validate_spec(_sw(filters={"trend_ma": {"period": "30"}}), [])
    assert c["filters"] == {}
    both = _sw(stop={"atr_multiple": 2, "swing_low": True})
    assert validate_spec(both, []) == (None, "stop needs one of atr_multiple or swing_low")
    assert validate_spec(_sw(stop={}), []) == (None, "no stop")


def test_swing_side_is_always_long():
    for side in ("short", "flat", None, 5):
        c, why = validate_spec(_sw(side=side), [])
        assert c["side"] == "long", why


def test_swing_needs_max_hold():
    raw = _sw()
    del raw["max_hold_days"]
    assert validate_spec(raw, []) == (None, "no max hold")
    assert validate_spec(_sw(max_hold_days={"days": "x"}), []) == (None, "no max hold")


def test_intraday_spec_unchanged_without_horizon():
    for h in (None, "intraday", "weekly", 5):
        c, _ = validate_spec(_ex(horizon=h), [])
        assert c == EXAMPLE and "horizon" not in c
    c, _ = validate_spec(_ex(max_hold_days={"days": 5}), [])
    assert "max_hold_days" not in c


def test_swing_regime_and_atr_filters():
    f = {"regime_is": {"regimes": ["risk_on", "risk_on"]}, "atr_pct": {"min": 3, "max": 2}}
    c, _ = validate_spec(_sw(filters=f), [])
    assert c["filters"] == {"regime_is": {"regimes": ["risk_on"]}} and load_ok(c)
    assert "in a risk_on market" in describe(c)


def test_duplicate_only_within_horizon():
    a, _ = validate_spec(SWING, [])
    assert validate_spec(_sw(setup={"breakout_n": {"days": 25}}), [{"slug": "a", "spec": a}]) \
        == (None, "duplicate of a")
    assert validate_spec(_sw(setup={"breakout_n": {"days": 40}}), [{"slug": "a", "spec": a}])[0] is not None
    intraday, _ = validate_spec(EXAMPLE, [])
    assert validate_spec(SWING, [{"slug": "i", "spec": intraday}])[0] is not None
    assert validate_spec(EXAMPLE, [{"slug": "a", "spec": a}])[0] is not None


def _swing_places(v):
    for k in ("horizon", "setup", "filters", "side", "stop", "target", "max_hold_days", "trail_atr"):
        yield {**SWING, k: v}
    yield {**SWING, "setup": {"pullback_ma": {"trend": v, "pull": v}}}
    yield {**SWING, "stop": {"atr_multiple": v, "swing_low": v}}
    yield {**SWING, "max_hold_days": {"days": v}, "trail_atr": {"multiple": v}}
    for f, params in SWING["filters"].items():
        yield {**SWING, "filters": {f: v}}
        yield {**SWING, "filters": {f: {k: v for k in params}}}
    yield {**SWING, "filters": {"regime_is": {"regimes": [v]}, "atr_pct": {"min": 1, "max": v}}}


@pytest.mark.parametrize("v", range(len(HOSTILE)))
def test_hostile_values_never_raise_swing(v):
    for raw in _swing_places(HOSTILE[v]):
        out = validate_spec(raw, [{"slug": "a", "spec": HOSTILE[v]}, HOSTILE[v], {"slug": "s", "spec": SWING}])
        assert isinstance(out, tuple) and len(out) == 2
        if out[0] is not None:
            assert load_ok(out[0])
