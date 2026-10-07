import copy

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
    # volume_confirm's grid starts at 1.2 (step .25), so 2.0 snaps to 1.95 by the snap rule.
    assert why == "" and load_ok(clean) and clean["filters"]["volume_confirm"] == {"multiple": 1.95}
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
    assert c["time_stop"] == {"minutes": 105} and load_ok(c)
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
