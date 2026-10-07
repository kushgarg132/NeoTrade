"""Strategies built from block specs (backend/strategies/blocks/): the active
specs are handed in as plain data (`set_active`), and BlockStrategy interprets
one spec bar by bar. I/O-free and clock-free like everything under strategies/;
the caller loads the docs and the Nifty regime.

Spec shape: {"setup": {block: params}, "filters": {block: params, ...} (in spec
order), "side": "long"|"short", "stop": {...}, "target": {...}, "time_stop": {...}}.
"""
import copy
import logging
from datetime import date
from typing import Callable, Optional

from backend.core.models import Intent, Side
from backend.engine.protocols import StrategySpec
from backend.engine.session import IST
from backend.strategies.base import TokenResolvingStrategy
from backend.strategies.blocks.blocks import filter_passes, setup_fires
from backend.strategies.blocks.state import SymbolState
from backend.strategies.blocks.vocab import EXITS, FILTERS, SETUPS
from backend.strategies.card import StrategyCard

logger = logging.getLogger(__name__)

_ACTIVE: list[dict] = []
_NEEDS = {"gap": "gap", "volume_spike": "volume_spike", "orb_break": "range_day"}


def set_active(docs: list[dict]) -> None:
    """Replaces the cache of `{"slug", "spec", "params"}` docs; registry builds from it."""
    _ACTIVE[:] = [dict(d) for d in docs]


def active() -> list[dict]:
    return list(_ACTIVE)


def _blocks_ok(blocks, vocab: dict) -> bool:
    return isinstance(blocks, dict) and all(
        n in vocab and isinstance(p, dict) and set(p) <= set(vocab[n]) for n, p in blocks.items())


def load_ok(spec: dict) -> bool:
    """Whether every block and param key in `spec` still exists in the vocabulary
    (a vocabulary change can orphan a stored spec). Does not clamp values."""
    try:
        setup, filters = spec["setup"], spec.get("filters") or {}
        if spec["side"] not in ("long", "short") or len(setup) != 1 or not spec.get("stop") or not spec.get("target"):
            return False
        # Blocks index their params directly, so setups and filters need every key.
        if not (_blocks_ok(setup, SETUPS) and _blocks_ok(filters, FILTERS)):
            return False
        if any(set(p) != {k for k, v in vocab[n].items() if v != ()}
               for vocab, blocks in ((SETUPS, setup), (FILTERS, filters)) for n, p in blocks.items()):
            return False
        return all(_blocks_ok({k: spec[k]}, EXITS) for k in ("stop", "target", "time_stop") if spec.get(k))
    except (KeyError, TypeError):
        return False


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _flat(spec: dict) -> dict[str, tuple]:
    """key -> (value, (lo, hi, step)) for every numeric param, keys as in PARAMS."""
    out = {}
    for kind, vocab, section in (("setup", SETUPS, spec["setup"]), ("filter", FILTERS, spec.get("filters") or {})):
        for block, params in section.items():
            for k, v in params.items():
                if _numeric(v):
                    out[f"{kind}.{block}.{k}"] = (v, vocab[block][k])
    for block in ("stop", "target", "time_stop"):
        for k, v in (spec.get(block) or {}).items():
            if _numeric(v):
                out[f"{block}.{block}.{k}"] = (v, EXITS[block][k])
    return out


def _set(spec: dict, key: str, value) -> None:
    kind, block, param = key.split(".")
    target = {"setup": spec["setup"], "filter": spec.get("filters")}.get(kind, spec)
    target[block][param] = value


class BlockStrategy(TokenResolvingStrategy):
    def __init__(self, slug: str, spec: dict, universe: list[str], symbol_for_token: dict[int, str],
                 params: dict | None = None, regime_of: Callable[[date], Optional[str]] | None = None,
                 sector_of: dict[str, str] | None = None, thesis: str = "AI-built strategy.") -> None:
        flat = _flat(spec)
        # Instance attributes: TokenResolvingStrategy reads self.PARAMS to filter overrides.
        self.PARAMS = {k: v for k, (v, _) in flat.items()}
        self.GRID = {}
        for k, (v, (lo, hi, step)) in flat.items():
            vals = [min(hi, max(lo, round(v + d * step, 4))) for d in (-1, 0, 1)]
            self.GRID[k] = list(dict.fromkeys(vals))
        super().__init__(universe, symbol_for_token, params)
        self.slug, self._regime_of, self._sector_of = slug, regime_of, sector_of or {}
        self._spec = copy.deepcopy(spec)
        for k, v in self.p.items():
            _set(self._spec, k, int(v) if isinstance(flat[k][1][2], int) else v)
        sp = self._spec
        self._setup, self._filters = next(iter(sp["setup"].items())), list((sp.get("filters") or {}).items())
        self._long = sp["side"] == "long"
        self._ema = {int(p["period"]) for n, p in [self._setup] if n == "ema_pullback"}
        self._rsi = {int(p["period"]) for n, p in [self._setup] if n == "rsi_cross"}
        self._range = {int(p["range_minutes"]) for n, p in [self._setup] if n == "orb_break"}
        self._needs_sector = any(n == "sector_rs" for n, _ in self._filters)
        self._states: dict[str, SymbolState] = {}
        self._entry = {}  # symbol -> entry fill time, for the time stop
        self._exit_sent: set[str] = set()
        self._entered: dict[str, date] = {}  # symbol -> IST day of its last entry
        self.CARD = self._card(thesis)
        self.spec = StrategySpec(name=f"built:{slug}", mode="INTRADAY", timeframe="5m", warmup_bars=20,
                                 universe=list(universe))

    def _card(self, thesis: str) -> StrategyCard:
        name, params = self._setup
        regimes = next((p["regimes"] for n, p in self._filters if n == "regime_is"), None)
        reversion = name == "rsi_cross" or (name == "vwap_cross" and params["mode"] == "reclaim")
        return StrategyCard(
            style="breakout" if name == "orb_break" else "reversion" if reversion else "momentum",
            regimes=list(regimes) if regimes else ["risk_on", "neutral", "risk_off"],
            needs=[_NEEDS.get(name, "trend_day")], best_when=thesis,
            avoid_when="Outside its time window or regimes.",
            typical_hold_minutes=int((self._spec.get("time_stop") or {}).get("minutes") or 120))

    def on_fill(self, ctx, fill) -> None:
        pos = ctx.position(fill.symbol)
        if pos is None or pos.quantity == 0:
            self._entry.pop(fill.symbol, None)
            self._exit_sent.discard(fill.symbol)
        else:
            self._entry.setdefault(fill.symbol, fill.timestamp)

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None:
            return
        s = self._states.get(symbol)
        if s is None:
            s = self._states[symbol] = SymbolState(self._ema, self._rsi, self._range)
        s.update(bar)
        pos = ctx.position(symbol)
        if pos is not None and pos.quantity != 0:
            self._maybe_time_stop(ctx, bar, symbol, pos)
        elif not bar.warmup and (intent := self._entry_intent(bar, symbol, s)) is not None:
            ctx.submit(intent)

    def _maybe_time_stop(self, ctx, bar, symbol, pos) -> None:
        minutes = (self._spec.get("time_stop") or {}).get("minutes")
        start = self._entry.get(symbol)
        if not minutes or start is None or symbol in self._exit_sent:
            return
        if (bar.timestamp - start).total_seconds() >= minutes * 60:
            self._exit_sent.add(symbol)  # once; on_fill clears it when flat
            ctx.submit(Intent(symbol=symbol, side=Side.SELL if pos.quantity > 0 else Side.BUY, strength=0.6,
                              reason_codes=[f"built:{self.slug}", "time_stop"]))

    def _entry_intent(self, bar, symbol: str, s: SymbolState) -> Optional[Intent]:
        name, params = self._setup
        day = bar.timestamp.astimezone(IST)
        if self._entered.get(symbol) == day.date():  # the setup can stay true all day; one entry per day
            return None
        if not setup_fires(name, params, s, self._spec["side"]):
            return None
        regime = self._regime_of(day.date()) if self._regime_of else None
        sector_rs = self._sector_rs(symbol, s) if self._needs_sector else None
        for fname, fparams in self._filters:
            if not filter_passes(fname, fparams, s, regime, sector_rs, day.time()):
                return None
        close, sign = s.close, 1 if self._long else -1
        stop_cfg = self._spec["stop"]
        if "atr_multiple" in stop_cfg:
            if s.atr is None:
                return None
            stop = close - sign * stop_cfg["atr_multiple"] * s.atr
        else:
            stop = bar.low if self._long else bar.high
        risk = (close - stop) * sign
        if risk <= 0:
            return None
        self._entered[symbol] = day.date()
        return Intent(symbol=symbol, side=Side.BUY if self._long else Side.SELL, strength=0.6,
                      reason_codes=[f"built:{self.slug}", name, *[n for n, _ in self._filters]],
                      stop_hint=stop, target_hint=close + sign * self._spec["target"]["r_multiple"] * risk)

    def _sector_rs(self, symbol: str, s: SymbolState) -> Optional[float]:
        """Mean session return of the symbol's sector minus the universe's, in %."""
        sector = self._sector_of.get(symbol)
        rets, mine = [], []
        for sym, st in self._states.items():
            if st.day == s.day and st.open:
                r = (st.close / st.open - 1) * 100
                rets.append(r)
                if self._sector_of.get(sym) == sector:
                    mine.append(r)
        if sector is None or len(mine) < 3:
            return None
        return sum(mine) / len(mine) - sum(rets) / len(rets)
