"""The only gate between model output and the interpreter: turns a model-written spec into the
canonical shape (backend/strategies/built.py) or refuses it with a short reason. Everything it
returns passes `built.load_ok`; no I/O.
"""
import math

from backend.strategies.blocks.vocab import (EXITS, FILTERS, SETUPS, SWING_EXITS, SWING_FILTERS,
                                             SWING_SETUPS)

_MAX_FILTERS = 3
_SECTIONS = {"setup": SETUPS, "filters": FILTERS, "stop": EXITS, "target": EXITS}
_SWING_SECTIONS = {"setup": SWING_SETUPS, "filters": SWING_FILTERS, "stop": SWING_EXITS, "target": SWING_EXITS,
                   "max_hold_days": SWING_EXITS, "trail_atr": SWING_EXITS}


def _num(v) -> bool:
    """A real, finite number (bool, NaN, inf and ints too big for a float are not)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def _kind(spec: tuple) -> str:
    if not spec:
        return "flag"
    if spec[0] == "HH:MM":
        return "clock"
    return "choice" if isinstance(spec[0], str) else "numeric"


def _snap(v, spec):
    lo, hi, step = spec
    x = math.floor(min(hi, max(lo, v)) / step + 0.5) * step  # nearest multiple of step
    x = min(hi, max(lo, x))  # rounding can step outside the range
    return int(round(x)) if all(isinstance(n, int) for n in spec) else round(x, 4)


def _minutes(s) -> int | None:
    if not isinstance(s, str):
        return None
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def _clock(v, spec):
    lo, hi = _minutes(spec[1]), _minutes(spec[2])
    m = _minutes(v)
    if m is None:
        return None
    m = int(min(hi, max(lo, m)) / 5 + 0.5) * 5  # 5-minute marks (09:20 and 14:45 are on them)
    return f"{m // 60:02d}:{m % 60:02d}"


def _clean_params(vocab: dict, raw) -> dict | None:
    """Every non-flag param, clamped and snapped; unknown keys dropped; None if one is missing/invalid."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k, spec in vocab.items():
        kind, v = _kind(spec), raw.get(k)
        if kind == "flag":
            continue
        if kind == "numeric":
            v = _snap(v, spec) if _num(v) else None
        elif kind == "clock":
            v = _clock(v, spec)
        elif k == "regimes":  # the one multi-choice param: any non-empty subset
            v = list(dict.fromkeys(x for x in ([v] if isinstance(v, str) else v if isinstance(v, list) else [])
                                   if isinstance(x, str) and x in spec)) or None
        elif v not in spec:
            v = None
        if v is None:
            return None
        out[k] = v
    return out


def _clean_filter(name: str, raw, filters=FILTERS):
    vocab = filters[name]
    if not isinstance(raw, dict):  # shorthand: the bare value of the block's single param
        if len(vocab) != 1:
            return None
        raw = {next(iter(vocab)): raw}
    p = _clean_params(vocab, raw)
    if p is None:
        return None
    if name == "time_window" and p["start"] >= p["end"]:  # zero-padded, so string order is time order
        return None
    if name == "atr_pct" and p["min"] >= p["max"]:
        return None
    return p


def _clean_stop(raw):
    if not isinstance(raw, dict):
        return None, "no stop"
    atr = raw.get("atr_multiple")
    bar = raw.get("setup_bar") is True or raw.get("setup_bar") == {}
    if _num(atr) and bar:
        return None, "stop needs one of atr_multiple or setup_bar"
    if _num(atr):
        return {"atr_multiple": _snap(atr, EXITS["stop"]["atr_multiple"])}, ""
    return ({"setup_bar": True}, "") if bar else (None, "no stop")


def _flat(spec: dict) -> dict:
    """(section, block, param) -> value, for comparing two specs."""
    out = {}
    for sec in ("setup", "filters"):
        for b, ps in (spec.get(sec) or {}).items():
            out.update({(sec, b, k): v for k, v in ps.items()})
    for sec in ("stop", "target", "max_hold_days", "trail_atr"):
        out.update({(sec, sec, k): v for k, v in (spec.get(sec) or {}).items()})
    return out


def _is_dup(a: dict, b: dict) -> bool:
    """Same setup, filter names, side and every param (numbers within one step)."""
    try:
        swing = a.get("horizon") == "swing"
        if swing != (b.get("horizon") == "swing"):
            return False
        sections = _SWING_SECTIONS if swing else _SECTIONS
        if a["side"] != b["side"] or set(a["setup"]) != set(b["setup"]) \
                or set(a.get("filters") or {}) != set(b.get("filters") or {}):
            return False
        fa, fb = _flat(a), _flat(b)
        if fa.keys() != fb.keys():
            return False
        for (sec, blk, k), v in fa.items():
            w = fb[(sec, blk, k)]
            if _num(v) and _num(w):
                step = sections[sec][blk][k][2]
                if abs(v - w) > step + 1e-9:
                    return False
            elif v != w:
                return False
        return True
    except (KeyError, TypeError, AttributeError):
        return False  # a stale stored spec is simply not a duplicate


def _clean_swing_stop(raw):
    if not isinstance(raw, dict):
        return None, "no stop"
    atr = raw.get("atr_multiple")
    low = raw.get("swing_low") is True or raw.get("swing_low") == {}
    if _num(atr) and low:
        return None, "stop needs one of atr_multiple or swing_low"
    if _num(atr):
        return {"atr_multiple": _snap(atr, SWING_EXITS["stop"]["atr_multiple"])}, ""
    return ({"swing_low": True}, "") if low else (None, "no stop")


def _validate_swing(raw: dict, existing: list[dict]) -> tuple[dict | None, str]:
    """Swing counterpart of the intraday path: daily-bar vocabulary, long only, a max hold."""
    setups = raw.get("setup")
    setups = {n: p for n, p in setups.items() if n in SWING_SETUPS} if isinstance(setups, dict) else {}
    if len(setups) != 1:
        return None, "exactly one setup"
    name, params = next(iter(setups.items()))
    params = _clean_params(SWING_SETUPS[name], params)
    if params is None:
        return None, f"bad {name} params"
    exits = raw.get("exits") if isinstance(raw.get("exits"), dict) else {}
    pick = lambda k: raw.get(k) if raw.get(k) is not None else exits.get(k)  # noqa: E731
    stop, why = _clean_swing_stop(pick("stop"))
    if stop is None:
        return None, why
    target = _clean_params(SWING_EXITS["target"], pick("target"))
    if target is None:
        return None, "no target"
    hold = _clean_params(SWING_EXITS["max_hold_days"], pick("max_hold_days"))
    if hold is None:
        return None, "no max hold"
    filters = {}
    for n, p in (raw.get("filters") or {}).items() if isinstance(raw.get("filters"), dict) else []:
        if n in SWING_FILTERS and n not in filters and (c := _clean_filter(n, p, SWING_FILTERS)) is not None:
            filters[n] = c
    spec = {"horizon": "swing", "setup": {name: params}, "filters": dict(list(filters.items())[:_MAX_FILTERS]),
            "side": "long", "stop": stop, "target": target, "max_hold_days": hold}
    if (trail := _clean_params(SWING_EXITS["trail_atr"], pick("trail_atr"))) is not None:  # optional
        spec["trail_atr"] = trail
    for e in existing:
        if isinstance(e, dict) and _is_dup(spec, e.get("spec") or {}):
            return None, f"duplicate of {e.get('slug')}"
    return spec, ""


def validate_spec(raw: dict, existing: list[dict]) -> tuple[dict | None, str]:
    """`(clean_spec, "")` or `(None, reason)`. `existing` is `[{"slug", "spec"}, ...]`."""
    if not isinstance(raw, dict):
        return None, "not an object"
    if raw.get("horizon") == "swing":  # anything else is intraday
        return _validate_swing(raw, existing)
    setups = raw.get("setup")
    setups = {n: p for n, p in setups.items() if n in SETUPS} if isinstance(setups, dict) else {}
    if len(setups) != 1:
        return None, "exactly one setup"
    name, params = next(iter(setups.items()))
    params = _clean_params(SETUPS[name], params)
    if params is None:
        return None, f"bad {name} params"
    if raw.get("side") not in ("long", "short"):
        return None, "side must be long or short"
    exits = raw.get("exits") if isinstance(raw.get("exits"), dict) else {}
    pick = lambda k: raw.get(k) if raw.get(k) is not None else exits.get(k)  # noqa: E731
    stop, why = _clean_stop(pick("stop"))
    if stop is None:
        return None, why
    target = _clean_params(EXITS["target"], pick("target"))
    if target is None:
        return None, "no target"
    filters = {}
    for n, p in (raw.get("filters") or {}).items() if isinstance(raw.get("filters"), dict) else []:
        if n in FILTERS and n not in filters and (c := _clean_filter(n, p)) is not None:
            filters[n] = c
    spec = {"setup": {name: params}, "filters": dict(list(filters.items())[:_MAX_FILTERS]),
            "side": raw["side"], "stop": stop, "target": target}
    for e in existing:
        if isinstance(e, dict) and _is_dup(spec, e.get("spec") or {}):
            return None, f"duplicate of {e.get('slug')}"
    return spec, ""


def slugify(spec: dict) -> str:
    """e.g. `gap-down-vwap-above-long`: setup, its choice param, first filter, side; <= 40 chars.
    Swing slugs start `swing-`."""
    name, params = next(iter(spec["setup"].items()))
    parts = [name, *[v for v in params.values() if isinstance(v, str)][:1]]
    for fname, fp in list((spec.get("filters") or {}).items())[:1]:
        parts += [fname.removeprefix("price_vs_"), *[v for v in fp.values() if isinstance(v, str)
                                                    and not v[:1].isdigit()][:1]]
    parts.append(spec["side"])
    if spec.get("horizon") == "swing":
        parts.insert(0, "swing")
    return "-".join(parts).replace("_", "-")[:40].strip("-")


def _g(v) -> str:
    return f"{v:g}"


def _12h(hhmm: str) -> str:
    h, m = divmod(_minutes(hhmm), 60)
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


_SETUP_WORDS = {
    "orb_break": lambda p: f"price breaks out of the first {_g(p['range_minutes'])}-minute range",
    "gap": lambda p: f"the stock gapped {p['direction']} at least {_g(p['min_pct'])}%",
    "vwap_cross": lambda p: f"price {p['mode']}s VWAP",
    "rsi_cross": lambda p: f"RSI({_g(p['period'])}) crosses {p['direction']} through {_g(p['level'])}",
    "ema_pullback": lambda p: f"price pulls back to the {_g(p['period'])}-period EMA",
    "volume_spike": lambda p: f"volume spikes to {_g(p['multiple'])}× normal",
}
_FILTER_WORDS = {
    "regime_is": lambda p: f"in a {' or '.join(p['regimes'])} market",
    "sector_rs": lambda p: f"with its sector at least {_g(p['min'])}% ahead of the market",
    "atr_pct": lambda p: f"with ATR between {_g(p['min'])}% and {_g(p['max'])}% of price",
    "price_vs_vwap": lambda p: f"is {p['side']} VWAP",
    "volume_confirm": lambda p: f"on {_g(p['multiple'])}× volume",
}


_SWING_SETUP_WORDS = {
    "breakout_n": lambda p: f"close above the {_g(p['days'])}-day high",
    "pullback_ma": lambda p: f"pullback to the {p['pull']}-day average, above the {p['trend']}-day average",
    "rsi2_dip": lambda p: f"2-day RSI below {_g(p['level'])} while above the 200-day average",
    "gap_hold": lambda p: f"gap up of at least {_g(p['min_pct'])}% that holds",
    "momentum_rank": lambda p: f"top {_g(p['top_pct'])}% by {p['lookback']}-day return",
    "volume_breakout": lambda p: f"volume ≥ {_g(p['multiple'])}× normal, closing near the day's high",
}
_SWING_FILTER_WORDS = {
    "trend_ma": lambda p: f"above the {p['period']}-day average",
    "regime_is": _FILTER_WORDS["regime_is"],
    "sector_rs": _FILTER_WORDS["sector_rs"],
    "atr_pct": _FILTER_WORDS["atr_pct"],
    "liquidity": lambda p: f"turnover of at least ₹{_g(p['min_cr'])} crore a day",
}


def _describe_swing(spec: dict) -> str:
    name, params = next(iter(spec["setup"].items()))
    text = f"Swing, long: {_SWING_SETUP_WORDS[name](params)}"
    for n, p in (spec.get("filters") or {}).items():
        text += ", " + _SWING_FILTER_WORDS[n](p)
    stop = spec["stop"]
    text += "; stop " + (f"{_g(stop['atr_multiple'])}× ATR" if "atr_multiple" in stop else "below the 5-day low")
    text += f", target {_g(spec['target']['r_multiple'])}R"
    if trail := spec.get("trail_atr"):
        text += f", trailing {_g(trail['multiple'])}× ATR"
    return text + f", out after {_g(spec['max_hold_days']['days'])} days."


def describe(spec: dict) -> str:
    """One plain-words sentence for the spec."""
    if spec.get("horizon") == "swing":
        return _describe_swing(spec)
    name, params = next(iter(spec["setup"].items()))
    filters = spec.get("filters") or {}
    text = f"{spec['side'].capitalize()} when {_SETUP_WORDS[name](params)}"
    phrases = [_FILTER_WORDS[n](p) for n, p in filters.items() if n in _FILTER_WORDS]
    if phrases:
        text += " and " + " ".join(phrases)
    if tw := filters.get("time_window"):
        text += f", {_12h(tw['start'])}–{_12h(tw['end'])}"
    stop = spec["stop"]
    stop_text = f"{_g(stop['atr_multiple'])}× ATR" if "atr_multiple" in stop else "the setup bar"
    text += f"; stop {stop_text}, target {_g(spec['target']['r_multiple'])}R"
    return text + "."
