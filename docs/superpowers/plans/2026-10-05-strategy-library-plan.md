# Strategy Library + Four News-Aware Intraday Strategies Implementation Plan (Phase 15.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every strategy carries a descriptive card, a live catalog joins those cards with each strategy's real record for a user, and four new intraday strategies (gap-and-go, gap-fill fade, trend-day pullback, sector relative strength) join the default set on paper.

**Architecture:** Static `CARD`s live on strategy classes (I/O-free). `backend/learning/library.py` builds live cards from the backtest gate, the paper gate, learned rules and attribution. News reaches the gap strategies as a per-day catalyst map (`{date_iso: {symbol: direction}}`) injected at construction, built by `backend/datalayer/catalysts.py` from scored `news_items`; sector relative strength compares a stock to its sector *peers* in the same run (sector map from the Nifty 200 file), so no index feed is needed.

**Tech Stack:** Python 3.11, FastAPI, Motor/MongoDB (mongomock_motor in tests), pandas, pydantic v2, pytest (asyncio auto), LangChain `StructuredTool` for chat.

**Spec:** `docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md` (section 1 + build-order step 1)

## Global Constraints

- Nothing under `backend/strategies/` does I/O or reads the wall clock (`test_no_network_in_strategies.py`, `test_no_datetime_now.py`). Catalysts and sector maps are constructor arguments.
- Every `Intent` has non-empty `reason_codes`; strategies never size (`size_intents` does).
- `composite.py` stays the only conviction formula; strategy `strength` values are fixed constants below.
- New strategies paper-trade only until the backtest gate and paper gate pass — no gate change.
- Card `regimes` use the datalayer regime labels: `risk_on`, `neutral`, `risk_off`.
- Card `needs` values: `gap`, `volume_spike`, `range_day`, `trend_day`, `catalyst`, `sector_move`.
- Catalyst materiality: impact ≥ `MATERIALITY_THRESHOLD` (6, `backend/strategies/longterm/analyst_verdict.py`).
- Every LLM prompt lives in `backend/prompts/` (none added here).
- Tests: `cd /home/ubuntu/projects/NeoTrade && python3 -m pytest backend/tests -q -p no:cacheprovider`.
- Deploy mode this session: **direct** — commit subjects end `[skip ci]`; rebuild `backend ingest` in `/home/ubuntu/deploys/NeoTrade` after `git pull --ff-only`.

## Review Focus

1. A gap strategy on the **first session in history** (no prior-day bars) — must stay silent, not crash on a missing prior close. Pinned in Task 3.
2. A catalyst map keyed by a **different date** than the bar's session — `gap_and_go` must ignore yesterday's catalyst. Pinned in Task 3.
3. Sector relative strength with **fewer than `min_peers` peers having bars today** — silent. Pinned in Task 6.
4. `catalog()` for a **brand-new user** (no trades, no learning_state, no backtests) — every card present with `None`/empty stats, no KeyError. Pinned in Task 7.
5. A **news item with a naive `published_at`** or impacts on sectors only — loader must not crash and must ignore non-symbol impacts. Pinned in Task 2.

---

### Task 1: Static strategy cards

**Files:**
- Create: `backend/strategies/card.py`
- Modify: every strategy class in `backend/strategies/intraday/*.py` and `backend/strategies/longterm/*.py` (add `CARD`)
- Test: `backend/tests/test_strategy_cards.py`

**Interfaces:**
- Produces: `class StrategyCard(BaseModel)` (frozen, `extra="forbid"`): `style: Literal["breakout","reversion","momentum","options","value"]`, `regimes: list[Literal["risk_on","neutral","risk_off"]]` (min 1), `needs: list[Literal[...needs values...]]`, `best_when: str`, `avoid_when: str`, `typical_hold_minutes: int`. Each strategy class has `CARD: StrategyCard`.

Card values (decided here; `typical_hold_minutes` for LONGTERM is days × 375):

| Strategy | style | regimes | needs | hold |
|---|---|---|---|---|
| orb_breakout | breakout | risk_on, neutral | volume_spike | 90 |
| orb_options | options | risk_on, neutral | volume_spike | 60 |
| vwap_reversion | reversion | neutral | range_day | 45 |
| volume_surge | momentum | risk_on, neutral | volume_spike | 60 |
| rsi_momentum_scalp | momentum | risk_on, neutral | trend_day | 30 |
| technical_breakout | breakout | risk_on | volume_spike | 7500 |
| mean_reversion | reversion | neutral, risk_off | range_day | 3750 |
| macd_crossover | momentum | risk_on, neutral | trend_day | 7500 |
| cash_secured_put | options | neutral, risk_off | — | 11250 |
| quality_momentum | value | risk_on, neutral | — | 22500 |
| analyst_verdict | value | risk_on, neutral, risk_off | catalyst | 22500 |

`best_when`/`avoid_when`: one plain sentence each, written from the strategy's own module docstring.

- [ ] **Step 1: Write the failing test** `test_every_registered_strategy_has_a_card`: build `build_default_strategies(universe=["X"], quality_universe=["X"], quality_scores={"X": .6}, analyst_verdicts={"X": {}}, option_universe=["X"])`; for each, `isinstance(type(s).CARD, StrategyCard)`. Plus `test_card_rejects_unknown_regime`: `StrategyCard(style="breakout", regimes=["bull"], ...)` raises `ValidationError`.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_strategy_cards.py -q -p no:cacheprovider` — FAIL (no module `backend.strategies.card`).
- [ ] **Step 3: Implement** `card.py` and add `CARD = StrategyCard(...)` to each of the 11 classes per the table.
- [ ] **Step 4: Run** the test file — PASS.
- [ ] **Step 5: Commit** `feat(strategies): a card describing each strategy [skip ci]`

---

### Task 2: Catalyst map from scored news

**Files:**
- Create: `backend/datalayer/catalysts.py`
- Test: `backend/tests/test_datalayer_catalysts.py`

**Interfaces:**
- Produces: `async def catalyst_map(db, start: date, end: date) -> dict[str, dict[str, float]]` — `{ist_date_iso: {SYMBOL: direction}}` for every IST weekday `d` in `[start, end]`.

Rule: for day `d`, consider `news_items` with `status == "SCORED"` and `published_at` in `[d-1 at 15:30 IST, d at 09:15 IST)` (for Monday, from Friday 15:30). For each `impacts[]` entry with `type == "symbol"` and `impact >= MATERIALITY_THRESHOLD`, keep per symbol the `direction` of the highest-impact entry. Treat a naive `published_at` as UTC.

- [ ] **Step 1: Write failing tests** (mongomock `mongo` fixture as in `test_datalayer_news.py`):
  - `test_overnight_material_symbol_news_becomes_a_catalyst`: item published 2026-10-05 20:00 IST, impact 8 direction 0.7 on `TCS` → `catalyst_map(db, date(2026,10,6), date(2026,10,6)) == {"2026-10-06": {"TCS": 0.7}}`.
  - `test_monday_reaches_back_to_friday_close`: item Saturday 11:00 IST → appears under Monday.
  - `test_ignores_weak_sector_and_after_open_items`: impact 5 on symbol, impact 9 on a sector, symbol item at 09:20 IST → `{"2026-10-06": {}}`.
  - `test_strongest_impact_wins_and_naive_time_is_utc`: two items on `INFY` (impact 7 dir -0.4, impact 9 dir 0.6, one with naive `published_at`) → `0.6`.
- [ ] **Step 2: Run** — FAIL (module missing).
- [ ] **Step 3: Implement** `catalyst_map` (one `find` over the whole window, bucket in Python; use `backend.engine.session.IST`).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(datalayer): overnight news catalysts per day [skip ci]`

---

### Task 3: `gap_and_go` strategy (+ shared gap helper)

**Files:**
- Create: `backend/strategies/intraday/gaps.py` (helper), `backend/strategies/intraday/gap_and_go.py`
- Test: `backend/tests/test_gap_strategies.py`

**Interfaces:**
- Produces (`gaps.py`): `SESSION_LOOKBACK_BARS = 160`; `def split_sessions(history: list[Bar]) -> tuple[list[Bar], list[Bar]]` → (today's bars, prior session's bars; `[]` if none); `def gap_pct(today: list[Bar], prior: list[Bar]) -> Optional[float]` = `(today[0].open / prior[-1].close - 1) * 100`, `None` when `prior` is empty.
- Produces: `class GapAndGoStrategy(TokenResolvingStrategy)`, `__init__(universe, symbol_for_token, params=None, catalysts: dict[str, dict[str, float]] | None = None)`, `spec.name = "gap_and_go"`, INTRADAY, `5m`, `warmup_bars=4`. `PARAMS = {"gap_pct": 2.0, "volume_mult": 1.5, "range_minutes": 15}`, `GRID = {"gap_pct": [1.5, 2.0, 3.0], "volume_mult": [1.0, 1.5, 2.0]}`. CARD: momentum; risk_on, neutral; [gap, catalyst, volume_spike]; hold 120.

Signal (long; mirror for short with `direction < 0`, gap ≤ −gap_pct, break below range low, stop range high):
catalyst `= catalysts.get(today[0].timestamp.date().isoformat(), {}).get(symbol)`; require `catalyst > 0`, `gap_pct >= p.gap_pct`, current bar after the opening range, `current.close > range_high`, `min(low of bars after range) >= range_low`, `current.volume >= volume_mult * mean(range volumes)`. Intent: `strength=0.7`, `reason_codes=["gap_and_go", "news_catalyst"]`, `stop_hint=range_low`, `target_hint=close + 2*(close - range_low)`.

- [ ] **Step 1: Write failing tests** using the `_bars`/`_run` helpers copied from `test_strategies_ported.py` (5m bars; build a prior session ending at 100 then a session opening at 103):
  - `test_gap_and_go_buys_a_catalysed_gap_that_breaks_its_range` → one BUY, `reason_codes == ["gap_and_go", "news_catalyst"]`, `stop_hint == range_low`.
  - `test_gap_and_go_sells_a_negative_catalysed_gap_down` → one SELL.
  - `test_gap_and_go_silent_without_catalyst_or_on_another_days_catalyst` (catalyst keyed to the prior date) → `[]`.
  - `test_gap_and_go_silent_on_the_first_session_in_history` (no prior bars) → `[]`.
  - `test_gap_and_go_silent_when_range_low_broken_first` → `[]`.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_gap_strategies.py -q -p no:cacheprovider` — FAIL.
- [ ] **Step 3: Implement** `gaps.py` and `gap_and_go.py` following `orb_breakout.py`'s shape.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(strategies): gap-and-go on overnight news catalysts [skip ci]`

---

### Task 4: `gap_fill_fade` strategy

**Files:**
- Create: `backend/strategies/intraday/gap_fill_fade.py`
- Test: `backend/tests/test_gap_strategies.py` (append)

**Interfaces:**
- Consumes: `split_sessions`, `gap_pct`, `SESSION_LOOKBACK_BARS` from Task 3.
- Produces: `class GapFillFadeStrategy(TokenResolvingStrategy)`, same constructor as `GapAndGoStrategy`, `spec.name = "gap_fill_fade"`. `PARAMS = {"gap_pct": 1.5, "range_minutes": 15}`, `GRID = {"gap_pct": [1.0, 1.5, 2.5]}`. CARD: reversion; neutral, risk_off; [gap]; hold 90.

Signal (gap up → SELL; mirror gap down → BUY): `gap_pct >= p.gap_pct`; no catalyst **in the gap's direction** for that day/symbol (a catalyst `> 0` blocks fading a gap up; `< 0` blocks fading a gap down); after the range, `current.close < range_low` (failed to hold). Intent: `strength=0.6`, `reason_codes=["gap_fill_fade"]`, `stop_hint=range_high`, `target_hint=prior[-1].close`. Silent if `target_hint` is not on the profitable side of `close`.

- [ ] **Step 1: Write failing tests**:
  - `test_gap_fill_fade_sells_an_uncatalysed_gap_up_that_fails` → SELL, `target_hint == prior close`.
  - `test_gap_fill_fade_buys_a_failed_gap_down`.
  - `test_gap_fill_fade_will_not_fade_a_gap_its_news_supports` (catalyst +0.8 on gap up) → `[]`.
  - `test_gap_fill_fade_silent_on_the_first_session_in_history` → `[]`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(strategies): fade gaps the news does not support [skip ci]`

---

### Task 5: `trend_day_pullback` strategy

**Files:**
- Create: `backend/strategies/intraday/trend_day_pullback.py`
- Test: `backend/tests/test_trend_day_pullback.py`

**Interfaces:**
- Produces: `class TrendDayPullbackStrategy(TokenResolvingStrategy)`, standard constructor, `spec.name = "trend_day_pullback"`, INTRADAY, `5m`, `warmup_bars=12`. `PARAMS = {"ema_fast": 9, "ema_slow": 20, "slope_bars": 6}`, `GRID = {"slope_bars": [4, 6, 8]}`. CARD: momentum; risk_on, neutral; [trend_day]; hold 60.

Signal on today's session bars only (`Indicators.calculate_all` for `vwap`/`atr_14`; `Indicators.ema(df.close, ema_slow)` for the slow EMA): long when `close > vwap`, `ema_slow[-1] > ema_slow[-1 - slope_bars]`, previous bar `low <= max(ema_fast, ema_slow)` and `close >= ema_slow` (touched and held), current `close > previous high`. Mirror short. Intent: `strength=0.65`, `reason_codes=["trend_day_pullback"]`, `stop_hint=min(prev.low, ema_slow) - 0.5*atr` (long), `target_hint=close + 2*(close - stop)`. Silent if `atr` is NaN.

- [ ] **Step 1: Write failing tests**: rising 5m session (steady +0.3/bar for 14 bars), one dip bar touching EMA9, then a bar closing above the dip's high → one BUY with `reason_codes == ["trend_day_pullback"]` and `stop_hint < close`; mirrored falling series → SELL; `_flat_bars(20, "5m")` → `[]`; rising series without a pullback → `[]`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(strategies): buy the first pullback on a trend day [skip ci]`

---

### Task 6: `relative_strength_sector` strategy (peer-based)

**Files:**
- Create: `backend/strategies/intraday/relative_strength_sector.py`
- Test: `backend/tests/test_relative_strength_sector.py`

**Interfaces:**
- Produces: `class RelativeStrengthSectorStrategy(TokenResolvingStrategy)`, `__init__(universe, symbol_for_token, params=None, sector_of: dict[str, str] | None = None)`, `spec.name = "relative_strength_sector"`, INTRADAY, `5m`, `warmup_bars=6`. `PARAMS = {"sector_move_pct": 0.5, "lead_pct": 1.0, "min_peers": 3}`, `GRID = {"lead_pct": [0.75, 1.0, 1.5]}`. CARD: momentum; risk_on, neutral, risk_off; [sector_move]; hold 75.

Signal: `ret(s) = today_last_close / today_first_open - 1` (pct) over today's bars from `ctx.history`. Peers = other symbols in `self._universe` with the same `sector_of`, having ≥ `warmup_bars` bars today; silent if fewer than `min_peers`. `sector = mean(ret(peers))`. Long when `sector >= sector_move_pct`, `ret(stock) - sector >= lead_pct`, previous bar closed lower than the bar before it (a pullback), current close > previous high. Mirror short (sector ≤ −move, stock lags by ≥ lead). Intent: `strength=0.65`, `reason_codes=["relative_strength_sector"]`, `stop_hint=previous bar low` (long), `target_hint=close + 2*(close - stop)`. Symbols without a sector: silent.

- [ ] **Step 1: Write failing tests** with a 4-symbol `SimpleStrategyContext` (tokens 111..114, all sector `"IT"`; extend the `_run` helper to update several symbols' bars per timestamp):
  - `test_leader_of_a_rising_sector_is_bought_on_a_pullback` → BUY for the leader.
  - `test_laggard_of_a_falling_sector_is_sold`.
  - `test_silent_with_too_few_peers_trading_today` (only 2 peers have bars) → `[]`.
  - `test_silent_for_a_symbol_with_no_sector` → `[]`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(strategies): sector leaders and laggards against their peers [skip ci]`

---

### Task 7: Wire the four into the registry, the gate backtest and live runs

**Files:**
- Modify: `backend/strategies/registry.py` (`build_default_strategies`)
- Modify: `backend/risk/gate_backtest.py::backtest_for_gate`
- Modify: `backend/routers/trading.py::_launch_run`
- Test: `backend/tests/test_strategies_ported.py` (update count tests), `backend/tests/test_strategy_cards.py` (append)

**Interfaces:**
- Consumes: Tasks 2–6 classes; `catalyst_map`; `news_sources.universe_rows()`.
- Produces: `build_default_strategies(..., catalysts: dict[str, dict[str, float]] | None = None, sector_of: dict[str, str] | None = None)` — always includes the four new strategies (defaults `{}`), so the base set grows from 8 to **12** (8 → 12 intraday+longterm; INTRADAY 5m count 4 → 8).
- `def nifty200_sectors() -> dict[str, str]` in `backend/datalayer/news_sources.py` (symbol → sector from `universe_rows()`), used by both callers below.

Wiring:
- `backtest_for_gate`: pass `catalysts=await catalyst_map(db, (now - 365d).date(), now.date())` and `sector_of=nifty200_sectors()`.
- `_launch_run` (INTRADAY): pass `catalysts=await catalyst_map(db.db, today_ist, today_ist)` and `sector_of=nifty200_sectors()`. (The game plan in 15.2 will replace the catalyst source; same shape.)

- [ ] **Step 1: Update tests**: `test_build_default_strategies_returns_expected_eight` → rename `..._expected_twelve`, assert 12 and the INTRADAY/5m tuple appears 8 times; `test_build_default_strategies_includes_quality_momentum_when_provided` → 13. Add `test_new_strategies_get_catalysts_and_sectors`: `build_default_strategies(universe=["TCS"], catalysts={"2026-10-06": {"TCS": .5}}, sector_of={"TCS": "IT"})` → the `gap_and_go` instance's catalysts and the `relative_strength_sector` instance's `sector_of` equal the inputs.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_strategies_ported.py backend/tests/test_strategy_cards.py -q -p no:cacheprovider` — FAIL.
- [ ] **Step 3: Implement** registry args, `nifty200_sectors`, and both call sites.
- [ ] **Step 4: Run the full suite** — all pass (fix any other test that counted strategies, e.g. settings/chat name lists).
- [ ] **Step 5: Commit** `feat(strategies): four news-aware intraday strategies join the default set [skip ci]`

---

### Task 8: Live catalog, API and chat tool

**Files:**
- Create: `backend/learning/library.py` (I/O lives here, not under `backend/strategies/`)
- Modify: `backend/routers/settings.py` (new route), `backend/chat/tools.py` (new tool)
- Test: `backend/tests/test_strategy_library.py`

**Interfaces:**
- Consumes: `StrategyCard`; `BacktestGateStore.latest`; `paper_records`; `load_rules`; `_closed_trades`/`_state` from `learning/adapt.py`; `attribute`; `backend.portfolio.service._nifty`; `PrefsStore`.
- Produces: `async def catalog(db, user_id: str, nifty: list, mode: Optional[Literal["INTRADAY","LONGTERM"]] = None) -> list[dict]`, one dict per registered strategy (same build call as `routers/settings.py::list_strategies`), sorted by name:

```
{name, mode, timeframe, card: {...StrategyCard...},
 backtest: {passed, profit_factor, max_drawdown, trades, run_at} | None,
 paper: {passed, checks},
 learned: {paused: bool, floor: float | None, skip_regimes: [str]},
 stats: {all: {trades, net, win_rate, profit_factor, shrunk} | None,
         by_trend: {"up": {...} | None, "down": {...} | None},
         by_reason: {code: {...}}},
 live_switch: bool}
```
- Route: `GET /strategies/library?mode=INTRADAY` → `{"strategies": catalog(...)}` (authenticated user).
- Chat tool `get_strategy_library(mode: Optional[Literal["INTRADAY","LONGTERM"]] = None)`, description: "The strategy library: what each strategy is for (style, regimes it suits, conditions it needs, when to avoid it) and its record for this user (backtest gate, paper record, learned pauses/floors, results by Nifty trend and by reason). Use for 'which strategy suits today' or 'how is X doing'."

- [ ] **Step 1: Write failing tests** (mongomock):
  - `test_catalog_for_a_new_user_has_every_strategy_and_empty_stats`: 12 cards, each `backtest is None`, `stats["all"] is None`, `learned == {"paused": False, "floor": None, "skip_regimes": []}`.
  - `test_catalog_joins_gate_paper_learning_and_attribution`: seed one passing `strategy_backtests` doc for `orb_breakout`, `learning_state` pausing `vwap_reversion` with floor 0.6 on `orb_breakout`, 12 closed paper trades on `orb_breakout` → `orb_breakout.backtest.passed is True`, `stats.all.trades == 12`, `learned.floor == 0.6`; `vwap_reversion.learned.paused is True`.
  - `test_catalog_filters_by_mode`: `mode="LONGTERM"` → only LONGTERM names.
  - `test_library_route_returns_the_users_catalog` via the app's test client pattern used in `tests/test_settings*.py`.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_strategy_library.py -q -p no:cacheprovider` — FAIL.
- [ ] **Step 3: Implement** `catalog`, the route and the chat tool (register next to `get_learning`).
- [ ] **Step 4: Run the full suite** — all pass.
- [ ] **Step 5: Commit** `feat(learning): live strategy library for the UI, chat and the planner [skip ci]`

---

### Task 9: Docs, deploy, verify

**Files:**
- Modify: `docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md` (record: live catalog lives in `backend/learning/library.py`; relative strength is peer-based — no index feed; catalysts come from `catalyst_map` until 15.2's plan)
- Modify: `docs/ROADMAP.md` (Phase 15 status: `15.1 done <date>`), `docs/ARCHITECTURE.md` (strategy list + library)

- [ ] **Step 1: Edit the three docs.**
- [ ] **Step 2: Full suite** — PASS.
- [ ] **Step 3: Commit + push** `docs: phase 15.1 strategy library landed [skip ci]`; `git push`.
- [ ] **Step 4: Deploy**: `cd /home/ubuntu/deploys/NeoTrade && git pull --ff-only && docker compose build backend ingest && docker compose up -d backend ingest`.
- [ ] **Step 5: Verify**: ingest logs `ingest: leader, starting`; `docker exec neotrade-backend python -c` calling `catalog(db, <a real user id>, [])` returns 12+ cards with no exception; `GET /settings/strategies` lists the four new names.
