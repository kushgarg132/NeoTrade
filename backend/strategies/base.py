"""Shared helpers for porting the legacy pandas-based strategies
(backend/components/quant/strategies.py) onto the Strategy protocol
(backend/engine/protocols.py). No I/O, no wall-clock reads, no network calls
belong in this module or anything under backend/strategies/ -- see
backend/tests/test_no_datetime_now.py and test_no_network_in_strategies.py.
"""

from typing import Optional

import pandas as pd

from backend.core.models import Bar


def bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    """Adapts `ctx.history(...)`'s bar list (oldest first) into the OHLCV
    DataFrame shape `Indicators.calculate_all` / `SupportResistance` /
    `TrendDetector` (backend/components/quant/) already expect -- those are
    pure pandas and there's no reason to reimplement the math bar-by-bar."""
    return pd.DataFrame({
        "timestamp": [b.timestamp for b in bars],
        "open": [b.open for b in bars],
        "high": [b.high for b in bars],
        "low": [b.low for b in bars],
        "close": [b.close for b in bars],
        "volume": [b.volume for b in bars],
    })


class TokenResolvingStrategy:
    """Base class for the 4 ported strategies.

    `Bar` (backend/core/models.py) only carries `instrument_token`, and
    `Strategy.on_bar(ctx, bar)`'s contract (backend/engine/protocols.py)
    doesn't thread a resolved symbol into the call -- `runner.run()` needs
    the exact same `symbol_for_token` translation for the exact same reason
    (see its docstring), so this just gives every ported strategy its own
    copy of that map rather than inventing a second mechanism. Callers
    (backend/strategies/registry.py) build it from the same Instrument list
    a real run's feed already knows about.
    """

    # A strategy's tunable thresholds and the variants the monthly re-tune
    # (backend/learning/retune.py) may try. `params` overrides the defaults
    # with the last accepted re-tune.
    PARAMS: dict = {}
    GRID: dict[str, list] = {}

    def __init__(self, universe: list[str], symbol_for_token: dict[int, str],
                 params: dict | None = None) -> None:
        self._universe = list(universe)
        self._symbol_for_token = symbol_for_token
        self.p = {**self.PARAMS, **{k: v for k, v in (params or {}).items() if k in self.PARAMS}}

    def extend_universe(self, symbols: list[str]) -> None:
        """Takes on new symbols mid-run (the game plan's stocks in play,
        backend/plan/expand.py). The caller maps their tokens in the run's
        shared symbol_for_token."""
        for symbol in symbols:
            if symbol not in self._universe:
                self._universe.append(symbol)
        self.spec.universe = list(self._universe)

    def symbol_for(self, bar: Bar) -> Optional[str]:
        symbol = self._symbol_for_token.get(bar.instrument_token)
        return symbol if symbol in self._universe else None

    def on_start(self, ctx) -> None:
        pass

    def on_fill(self, ctx, fill) -> None:
        pass
