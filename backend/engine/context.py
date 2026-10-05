"""Concrete StrategyContext, backed by an in-memory bar buffer that the
runner feeds incrementally, one bar at a time, as they arrive. It is never
pre-loaded with the full dataset -- there is no path for `history()` to
return a bar that hasn't been `update()`-d into the buffer yet, which is
what makes lookahead structurally impossible rather than merely against the
docstring.
"""

from datetime import datetime
from typing import Optional

from backend.core.clock import Clock
from backend.core.models import Bar, Intent, Position
from backend.engine.portfolio import Portfolio
from dataclasses import replace


class SimpleStrategyContext:
    """Buffer is keyed by symbol only, not (symbol, timeframe): the
    `history(symbol, n)` contract (from engine/protocols.py) takes no
    timeframe argument, and every feed in this task produces bars for a
    single timeframe per run (HistoricalFeed takes one `timeframe`). Keying
    by symbol alone is equivalent in that world and keeps this class honest
    to the method signature it actually implements.
    # ponytail: single-timeframe-per-run assumption. Revisit if a future
    # feed ever mixes timeframes for the same symbol within one run.

    Bar identifies instruments by `instrument_token`; Strategy/Intent/Order
    work in tradingsymbol strings. `symbol_for_token` is the translation the
    caller (the runner) supplies.
    """

    def __init__(
        self,
        clock: Clock,
        portfolio: Portfolio,
        symbol_for_token: dict[int, str],
    ) -> None:
        self._clock = clock
        self._portfolio = portfolio
        self._symbol_for_token = symbol_for_token
        self._bars: dict[str, list[Bar]] = {}
        self._intents: list[Intent] = []
        # Set by the runner around each strategy's on_bar, so every intent is
        # stamped with the strategy that actually emitted it.
        self.current_strategy: Optional[str] = None

    def update(self, bar: Bar) -> None:
        symbol = self._symbol_for_token.get(bar.instrument_token)
        if symbol is None:
            return
        self._bars.setdefault(symbol, []).append(bar)

    def now(self) -> datetime:
        return self._clock.now()

    def history(self, symbol: str, n: int) -> list[Bar]:
        if n <= 0:
            return []
        return self._bars.get(symbol, [])[-n:]

    def position(self, symbol: str) -> Optional[Position]:
        return self._portfolio.positions.get(symbol)

    def submit(self, intent: Intent) -> None:
        if intent.strategy is None and self.current_strategy is not None:
            intent = replace(intent, strategy=self.current_strategy)
        self._intents.append(intent)

    def drain_intents(self) -> list[Intent]:
        intents, self._intents = self._intents, []
        return intents
