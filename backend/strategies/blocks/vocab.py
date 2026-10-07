"""The closed vocabulary of the strategy builder: block -> {param: spec}.

Spec forms: numeric `(lo, hi, step)`; choice = tuple of allowed strings; clock time
`("HH:MM", earliest, latest)`; flag `()` (key present = on). The validator clamps to these.
"""

_TIME = ("HH:MM", "09:20", "14:45")
_REGIMES = ("risk_on", "neutral", "risk_off")

SETUPS = {
    "orb_break": {"range_minutes": (5, 30, 5)},
    "gap": {"direction": ("up", "down"), "min_pct": (0.5, 4.0, 0.25)},
    "vwap_cross": {"mode": ("reclaim", "lose")},
    "rsi_cross": {"period": (7, 21, 1), "level": (20, 80, 5), "direction": ("up", "down")},
    "ema_pullback": {"period": (9, 50, 1)},
    "volume_spike": {"multiple": (1.5, 5.0, 0.25)},
}

FILTERS = {
    "time_window": {"start": _TIME, "end": _TIME},
    "regime_is": {"regimes": _REGIMES},  # any non-empty subset
    "sector_rs": {"min": (-3.0, 3.0, 0.1)},
    "atr_pct": {"min": (0.3, 3.0, 0.1), "max": (0.5, 6.0, 0.1)},
    "price_vs_vwap": {"side": ("above", "below")},
    "volume_confirm": {"multiple": (1.2, 3.0, 0.25)},
}

EXITS = {
    "stop": {"atr_multiple": (0.5, 3.0, 0.25), "setup_bar": ()},  # one of the two
    "target": {"r_multiple": (1.0, 4.0, 0.25)},
    "time_stop": {"minutes": (15, 240, 15)},  # optional
}
