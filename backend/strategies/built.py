"""Strategies built from block specs (backend/strategies/blocks/): the active
specs are handed in as plain data (`set_active`), and BlockStrategy interprets
one spec bar by bar. I/O-free and clock-free like everything under strategies/;
the caller loads the docs and the Nifty regime.

Spec shape: {"setup": {block: params}, "filters": {block: params, ...} (in spec
order), "side": "long"|"short", "stop": {...}, "target": {...}}. Positions close at the stop, the target
or the 15:15 square-off (the engine has no strategy exit path).

A swing spec ("horizon": "swing", Phase 18.1) runs on daily bars as a LONGTERM strategy: the 4 PM
scan files its intents as proposals, which carry max_hold_days and trail_atr for the exit checker.
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
from backend.strategies.blocks import swing
from backend.strategies.blocks.swing_state import SwingState
from backend.strategies.blocks.vocab import (EXITS, FILTERS, SETUPS, SWING_EXITS, SWING_FILTERS,
                                             SWING_SETUPS)
from backend.strategies.card import StrategyCard

logger = logging.getLogger(__name__)

_ACTIVE: list[dict] = []
_NEEDS = {"gap": "gap", "volume_spike": "volume_spike", "orb_break": "range_day",
          "gap_hold": "gap", "volume_breakout": "volume_spike"}
_SWING_STYLE = {"breakout_n": "breakout", "volume_breakout": "breakout", "gap_hold": "breakout",
                "rsi2_dip": "reversion", "pullback_ma": "reversion", "momentum_rank": "momentum"}
_SESSION_MINUTES = 375  # one NSE session, 09:15-15:30
_MIN_CROSS_SECTION = 30  # a rank or sector read over fewer symbols is not the one that was tested
_SWING_GAP = 5  # trading days (daily bars seen) between two entries in one symbol


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
    (a vocabulary change can orphan a stored spec). Does not clamp values. A swing spec
    ("horizon": "swing") is checked against the swing vocabulary: long only, max hold required."""
    try:
        swing = spec.get("horizon", "intraday") == "swing"
        if "horizon" in spec and not swing:
            return False
        setups, filter_vocab, exits = (SWING_SETUPS, SWING_FILTERS, SWING_EXITS) if swing else (SETUPS, FILTERS, EXITS)
        setup, filters = spec["setup"], spec.get("filters") or {}
        allowed = {"setup", "filters", "side", "stop", "target"} | ({"horizon", "max_hold_days", "trail_atr"} if swing else set())
        if not set(spec) <= allowed:  # e.g. a dropped time_stop
            return False
        if spec["side"] not in (("long",) if swing else ("long", "short")) or len(setup) != 1 \
                or not spec.get("stop") or not spec.get("target"):
            return False
        if swing and (not spec.get("max_hold_days") or len(spec["stop"]) != 1):  # one of atr_multiple / swing_low
            return False
        # Blocks index their params directly, so setups and filters need every key.
        if not (_blocks_ok(setup, setups) and _blocks_ok(filters, filter_vocab)):
            return False
        if any(set(p) != {k for k, v in vocab[n].items() if v != ()}
               for vocab, blocks in ((setups, setup), (filter_vocab, filters)) for n, p in blocks.items()):
            return False
        return all(_blocks_ok({k: spec[k]}, exits) for k in ("stop", "target", *(k for k in ("max_hold_days", "trail_atr") if k in spec)))
    except (KeyError, TypeError):
        return False


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _flat(spec: dict) -> dict[str, tuple]:
    """key -> (value, (lo, hi, step)) for every numeric param, keys as in PARAMS."""
    out = {}
    swing = spec.get("horizon") == "swing"
    setups, filter_vocab, exits = (SWING_SETUPS, SWING_FILTERS, SWING_EXITS) if swing else (SETUPS, FILTERS, EXITS)
    for kind, vocab, section in (("setup", setups, spec["setup"]), ("filter", filter_vocab, spec.get("filters") or {})):
        for block, params in section.items():
            for k, v in params.items():
                if _numeric(v):
                    out[f"{kind}.{block}.{k}"] = (v, vocab[block][k])
    for block in ("stop", "target", "max_hold_days", "trail_atr"):  # the last two are swing only
        for k, v in (spec.get(block) or {}).items():
            if _numeric(v):
                out[f"{block}.{block}.{k}"] = (v, exits[block][k])
    return out


def _set(spec: dict, key: str, value) -> None:
    kind, block, param = key.split(".")
    target = {"setup": spec["setup"], "filter": spec.get("filters")}.get(kind, spec)
    target[block][param] = value


class BlockStrategy(TokenResolvingStrategy):
    def __init__(self, slug: str, spec: dict, universe: list[str], symbol_for_token: dict[int, str],
                 params: dict | None = None, regime_of: Callable[[date], Optional[str]] | None = None,
                 sector_of: dict[str, str] | None = None, thesis: str = "AI-built strategy.",
                 prev_closes: dict[str, dict[str, float]] | None = None) -> None:
        flat = _flat(spec)
        # Instance attributes: TokenResolvingStrategy reads self.PARAMS to filter overrides.
        self.PARAMS = {k: v for k, (v, _) in flat.items()}
        self.GRID = {}
        for k, (v, (lo, hi, step)) in flat.items():
            vals = [min(hi, max(lo, round(v + d * step, 4))) for d in (-1, 0, 1)]
            self.GRID[k] = list(dict.fromkeys(vals))
        super().__init__(universe, symbol_for_token, params)
        self.slug, self._regime_of, self._sector_of = slug, regime_of, sector_of or {}
        self.thesis = thesis
        self.prev_closes = prev_closes or {}  # ISO day -> symbol -> previous close, for live feeds
        self.base_spec = copy.deepcopy(spec)  # before params are applied, for retune variants
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
        self._swing = sp.get("horizon") == "swing"
        self._states: dict = {}  # intraday: today's session only (see on_bar); swing: every day
        self._entered: dict[str, date] = {}  # symbol -> IST day of its last entry
        self._days: dict[str, date] = {}  # swing: symbol -> IST day of its last bar
        self._since: dict[str, int] = {}  # swing: symbol -> daily bars seen since its last entry
        self.CARD = self._card(thesis)
        if self._swing:
            self.spec = StrategySpec(name=f"built:{slug}", mode="LONGTERM", timeframe="1d", warmup_bars=200,
                                     universe=list(universe))
        else:
            self.spec = StrategySpec(name=f"built:{slug}", mode="INTRADAY", timeframe="5m", warmup_bars=20,
                                     universe=list(universe))

    def _card(self, thesis: str) -> StrategyCard:
        name, params = self._setup
        regimes = next((p["regimes"] for n, p in self._filters if n == "regime_is"), None)
        if self._swing:
            return StrategyCard(
                style=_SWING_STYLE[name], regimes=list(regimes) if regimes else ["risk_on", "neutral", "risk_off"],
                needs=[_NEEDS.get(name, "trend_day")], best_when=thesis, avoid_when="Outside its regimes.",
                typical_hold_minutes=int(self._spec["max_hold_days"]["days"]) * _SESSION_MINUTES)
        reversion = name == "rsi_cross" or (name == "vwap_cross" and params["mode"] == "reclaim")
        return StrategyCard(
            style="breakout" if name == "orb_break" else "reversion" if reversion else "momentum",
            regimes=list(regimes) if regimes else ["risk_on", "neutral", "risk_off"],
            needs=[_NEEDS.get(name, "trend_day")], best_when=thesis,
            avoid_when="Outside its time window or regimes.",
            typical_hold_minutes=120)

    def on_bar(self, ctx, bar) -> None:
        symbol = self.symbol_for(bar)
        if symbol is None:
            return
        day = bar.timestamp.astimezone(IST).date()
        if self._swing:
            return self._on_daily_bar(ctx, bar, symbol, day)
        s = self._states.get(symbol)
        if s is None or s.day != day:
            # A fresh state each session, seeded only with the previous close: a backtest feeds
            # yesterday's bars and a live feed only today's, so carrying indicators over would make
            # the two disagree (R17). Warm-up (ATR 14 bars, volume average 20) is paid every morning.
            prev = s.close if s is not None else self.prev_closes.get(day.isoformat(), {}).get(symbol)
            s = self._states[symbol] = SymbolState(self._ema, self._rsi, self._range)
            s.update(bar, prev_close=prev)
        else:
            s.update(bar)
        pos = ctx.position(symbol)
        if (pos is not None and pos.quantity != 0) or bar.warmup:
            return
        if (intent := self._entry_intent(bar, symbol, s)) is not None:
            ctx.submit(intent)

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

    def _on_daily_bar(self, ctx, bar, symbol: str, day: date) -> None:
        s = self._states.setdefault(symbol, SwingState())
        s.update(bar)
        self._days[symbol] = day
        if symbol in self._since:
            self._since[symbol] += 1
        pos = ctx.position(symbol)
        if (pos is not None and pos.quantity != 0) or bar.warmup:
            return
        if self._since.get(symbol, _SWING_GAP) < _SWING_GAP:  # a fresh signal after a stop-out must wait
            return
        name, params = self._setup
        rank = self._rank_pct(symbol, int(params["lookback"]), day) if name == "momentum_rank" else None
        if not swing.setup_fires(name, params, s, rank):
            return
        regime = self._regime_of(day) if self._regime_of else None
        sector_rs = self._swing_sector_rs(symbol, day) if self._needs_sector else None
        for fname, fparams in self._filters:
            if not swing.filter_passes(fname, fparams, s, regime, sector_rs):
                return
        close, stop_cfg = s.close, self._spec["stop"]
        if "atr_multiple" in stop_cfg:
            if s.atr is None:
                return
            stop = close - stop_cfg["atr_multiple"] * s.atr
        else:  # swing_low: lowest low of the last 5 bars, today included
            prior = s.low_n(4)
            if prior is None:
                return
            stop = min(s.low, prior)
        risk = close - stop
        if risk <= 0:
            return
        self._since[symbol] = 0
        sp = self._spec
        ctx.submit(Intent(symbol=symbol, side=Side.BUY, strength=0.6,
                          reason_codes=[f"built:{self.slug}", name, *[n for n, _ in self._filters]],
                          stop_hint=stop, target_hint=close + sp["target"]["r_multiple"] * risk,
                          max_hold_days=int(sp["max_hold_days"]["days"]),
                          trail_atr=sp["trail_atr"]["multiple"] if sp.get("trail_atr") else None))

    def _day_returns(self, n: int, day: date) -> dict[str, float]:
        """n-day return of every symbol as of the previous session: within a day the feed delivers
        symbols in a fixed order, so today's closes would rank a symbol only against those before it.
        A symbol already updated today reads one bar back; one not yet updated, its last bar."""
        return {sym: r for sym, st in self._states.items()
                if (r := st.ret(n, ago=1 if self._days.get(sym) == day else 0)) is not None}

    def _rank_pct(self, symbol: str, n: int, day: date) -> Optional[float]:
        """0 = best n-day return of the cross-section (as of the previous session), 100 = worst."""
        rets = self._day_returns(n, day)
        if symbol not in rets or len(rets) < _MIN_CROSS_SECTION:
            return None
        better = sum(r > rets[symbol] for r in rets.values())
        return 100 * better / (len(rets) - 1)

    def _swing_sector_rs(self, symbol: str, day: date) -> Optional[float]:
        """Mean 20-day return of the symbol's sector minus the universe's, in %, as of the previous session."""
        sector = self._sector_of.get(symbol)
        if sector is None:
            return None
        rets = self._day_returns(20, day)
        mine = [r for sym, r in rets.items() if self._sector_of.get(sym) == sector]
        if len(rets) < _MIN_CROSS_SECTION or len(mine) < 3:
            return None
        return (sum(mine) / len(mine) - sum(rets.values()) / len(rets)) * 100

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
