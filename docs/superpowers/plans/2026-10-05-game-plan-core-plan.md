# AI Game Plan Core Implementation Plan (Phase 15.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each auto-intraday user gets an AI game plan at 08:45 IST that decides which (strategy, stock) pairs may open trades, how much risk, how many positions, which news names to add or whether to skip the day; the engine enforces it as a tightening-only gate, and a nightly replay scores plan-vs-no-plan.

**Architecture:** `backend/plan/` holds a pure validator (raw LLM JSON → clamped `TradePlan`, or the fallback), a store (Mongo `trade_plans` versions + Redis current copy + a daily call budget), a `PlanGate` read once per bar by `size_intents` next to `LearnedRules`, a builder (context → one `deep` call → validate → store), and a replay that runs the day's 5-minute bars twice through `run_backtest` (with the plan's versions, and without). Pre-open building hangs off the existing `autorun.tick`; the replay off the 16:00 `scheduler.run_daily_jobs`.

**Tech Stack:** Python 3.11, FastAPI, Motor/MongoDB (mongomock_motor in tests), Redis (FakeRedis in tests), pydantic v2, pytest (asyncio auto).

**Spec:** `docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md` (sections 2, 3 — except revisions, plan exits and mid-session adds, which are 15.3)

## Global Constraints

- The plan can only **remove or shrink** orders: never loosens a user cap, the kill switch, learned rules, the backtest gate, the paper gate, or the autopilot fence.
- Strategy exits and the 15:15 square-off are never blocked by the plan (only intents where `runner._opens(...)` is true are judged).
- A failed, invalid, over-budget or missing plan falls back to today's behaviour.
- `composite.py` stays the only conviction formula; `risk_multiplier` scales `risk_pct` after scoring.
- `risk_multiplier` clamped to **[0.25, 1.0]**; `add_symbols` ≤ **10**, Nifty 200 only; `rationale` 2–5 lines.
- `PLAN_LLM_CALLS_PER_DAY` setting, default **100**, Redis `plan:calls:<IST date>`; pre-open plans run in user order until the cap, then fallback.
- Every prompt lives in `backend/prompts/*.md` with front-matter `system:`; rendered by `backend.prompts.render`.
- LLM failures come back in-band (`"LLM_DISABLED"`, text starting `"Error generating response"`), not as exceptions.
- Every per-account record carries `user_id`.
- Tests: `cd /home/ubuntu/projects/NeoTrade && python3 -m pytest backend/tests -q -p no:cacheprovider`. Deploy mode: **direct** (`[skip ci]` subjects; rebuild `backend ingest` in `/home/ubuntu/deploys/NeoTrade`).

## Decisions this plan makes (spec silent or superseded)

- **No user `max_positions` pref exists** → cap is `MAX_PLAN_POSITIONS = 10`.
- **No pre-open gap % at 08:45** (NSE pre-open prices aren't in any feed here) → candidates carry overnight catalysts from `catalyst_map` instead.
- **Plan exits** are 15.3 (they only matter for revisions); the validator forces `exits=[]` for `trigger="pre_open"`/`"fallback"`.
- **Replay** runs inside the 16:00 daily pass (`scheduler.run_daily_jobs`), not a separate 16:30 job — 5-minute bars for the day exist by then.
- **Live routing is unchanged in 15.2.** The gate filters paper and live alike (it only tightens). The "4 weeks beating baseline" rule becomes `weeks_beating(db, user_id) -> int` for 15.4 to show; nothing routes on it yet.
- **`skip_day`** stops only the 08:45-planned **auto**-run; a manual `/trading/start` on a skip day still runs but the gate opens nothing (empty `allow`).

## Review Focus

1. LLM returns JSON wrapped in prose, or an `allow` entry naming a LONGTERM strategy / unknown symbol → dropped, plan still stored. Pinned in Task 1.
2. Two workers' `autorun.tick` both reach 08:45 → exactly one plan per user per day. Pinned in Task 5.
3. Redis plan key missing mid-run (expired, Redis flush) → gate falls back to "allow all", never blocks everything. Pinned in Task 3.
4. A user with no intraday run today, or a provider returning no 5-minute bars → replay skips that user, daily pass continues. Pinned in Task 6.
5. Plan allows a symbol the user already holds and the opening intent would exceed `max_positions` only because of that held symbol → adding to an existing position is not a new position. Pinned in Task 3.

---

### Task 1: `TradePlan` model, validator and fallback

**Files:**
- Create: `backend/plan/__init__.py` (empty), `backend/plan/validate.py`
- Test: `backend/tests/test_plan_validate.py`

**Interfaces:**
- Produces:
  - `MAX_PLAN_POSITIONS = 10`, `MAX_ADDS = 10`, `MIN_MULTIPLIER, MAX_MULTIPLIER = 0.25, 1.0`
  - `class TradePlan(BaseModel)`: `trigger: str`, `skip_day: bool = False`, `risk_multiplier: float = 1.0`, `max_positions: int = MAX_PLAN_POSITIONS`, `add_symbols: list[str] = []`, `allow: list[dict]` (each `{"symbol": str, "strategies": list[str], "catalyst": {"item_id": str, "direction": float} | None}`), `exits: list[dict] = []`, `rationale: list[str] = []`.
  - `def validate(raw: str | dict, *, trigger: str, strategies: set[str], universe: set[str], nifty200: set[str]) -> TradePlan` — raises `ValueError` only when `raw` has no parseable JSON object (use `backend.components.analyst.agent._extract_json`).
  - `def fallback_plan(strategies: set[str], universe: set[str], reason: str) -> TradePlan` — `trigger="fallback"`, every strategy on every universe symbol, multiplier 1, `rationale=[reason]`.

Rules (in order): symbols upper-cased; `add_symbols` kept only if in `nifty200` and not already in `universe`, first 10; allowed symbols = `universe ∪ add_symbols`; each `allow` entry kept only if its symbol is allowed, its `strategies` filtered to `strategies`, and at least one remains; duplicate symbols merged (union of strategies); `risk_multiplier` clamped; `max_positions` clamped to `[0, MAX_PLAN_POSITIONS]`; `exits` forced `[]` when trigger is `pre_open`/`fallback`; `rationale` trimmed to 5 lines of ≤ 200 chars.

- [ ] **Step 1: Write failing tests**
  - `test_clamps_only_tighten`: raw multiplier 3.0 → 1.0; 0.1 → 0.25; `max_positions` 50 → 10.
  - `test_drops_unknown_strategies_symbols_and_non_nifty_adds`: allow `[{"symbol":"tcs","strategies":["orb_breakout","macd_crossover","nope"]}, {"symbol":"ZZZ","strategies":["orb_breakout"]}]`, adds `["INFY","NOTNIFTY","TCS"]` with universe `{"TCS"}`, nifty200 `{"INFY","TCS"}`, strategies `{"orb_breakout","gap_and_go"}` → allow `[{"symbol":"TCS","strategies":["orb_breakout"],"catalyst":None}]`, adds `["INFY"]`.
  - `test_json_wrapped_in_prose_is_parsed` (`'Here: {"skip_day": true, "rationale": ["CPI at 10"]} thanks'`) → `skip_day is True`.
  - `test_no_json_raises_value_error`.
  - `test_pre_open_plan_has_no_exits`.
  - `test_fallback_allows_everything_at_full_risk`: 2 strategies × 2 symbols → 2 allow entries each with both strategies, multiplier 1.0, `trigger == "fallback"`.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_plan_validate.py -q -p no:cacheprovider` — FAIL (module missing).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(plan): game plan model, validator and fallback [skip ci]`

---

### Task 2: Plan store and call budget

**Files:**
- Create: `backend/plan/store.py`
- Modify: `backend/configs/settings.py` (`PLAN_LLM_CALLS_PER_DAY: int = 100`)
- Test: `backend/tests/test_plan_store.py` (use `FakeRedis` from `backend/tests/test_datalayer_news.py`, mongomock)

**Interfaces:**
- Consumes: `TradePlan` (Task 1).
- Produces:
  - `COLLECTION = "trade_plans"`, `KEY = "plan:{}:{}"` (user_id, IST date iso), `CALLS_KEY = "plan:calls:{}"`
  - `async def save(db, redis, user_id: str, day: date, plan: TradePlan, now: datetime) -> dict` — inserts `{user_id, date: day.isoformat(), version: previous+1 (1 first), at: now, **plan.model_dump()}`; sets Redis `KEY` to the doc as JSON (drop `_id`, `at` as ISO), TTL until 01:00 IST next day; returns the doc.
  - `async def current(redis, user_id: str, day: date) -> Optional[dict]`
  - `async def versions(db, user_id: str, day: date) -> list[dict]` (ascending version, `at` aware UTC)
  - `async def reserve_call(redis, day: date) -> bool` — `INCR` then compare to `settings.PLAN_LLM_CALLS_PER_DAY`; over cap → `DECR` back and `False`; key TTL 2 days.

- [ ] **Step 1: Write failing tests**: `test_save_versions_and_mirrors_to_redis` (two saves → versions 1, 2; `current` returns version 2; `versions` returns both in order); `test_budget_stops_at_the_cap` (cap monkeypatched to 2 → `[True, True, False]`, counter stays 2).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(plan): versioned plan store and daily call budget [skip ci]`

---

### Task 3: `PlanGate` in the engine

**Files:**
- Create: `backend/plan/gate.py`
- Modify: `backend/engine/runner.py` (`size_intents` gains `plan: Optional[PlanGate] = None`; `run()` gains `plan` and calls `await plan.refresh(bar.timestamp)` once per bar before sizing), `backend/engine/backtest.py` (`run_backtest(..., plan=None)` passes it through)
- Test: `backend/tests/test_plan_gate.py`

**Interfaces:**
- Produces:
  - `PlanSource = Callable[[datetime], Awaitable[Optional[dict]]]`
  - `class PlanGate`: `__init__(self, source: PlanSource)`; `async refresh(self, now: datetime) -> None` (calls `source` at most once per distinct `now`); `blocks(self, strategy: Optional[str], symbol: str, holding: bool, open_positions: int) -> Optional[str]`; property `multiplier -> float` (1.0 with no plan).
  - `def redis_source(redis, user_id: str) -> PlanSource` (reads `store.current` for `now`'s IST date)
  - `def versions_source(versions: list[dict]) -> PlanSource` (latest version with `at <= now`, else None)

`blocks` rules: no plan → None. `skip_day` → `"plan: skip day"`. `(strategy, symbol)` not in `allow` → `"plan: not in today's plan"`. `not holding and open_positions >= max_positions` → `"plan: max positions"`. In `size_intents`: apply only when `_opens(intent, portfolio, mode)` and `mode == "INTRADAY"`; `holding` = symbol has a non-zero position; `open_positions` = count of non-zero positions; after scoring, `risk_pct = BASE_RISK_PCT * scored.final * plan.multiplier`.

- [ ] **Step 1: Write failing tests**
  - `test_no_plan_allows_everything` (source returns None) → `blocks(...) is None`, `multiplier == 1.0`.
  - `test_blocks_pairs_outside_allow_and_skip_day`.
  - `test_max_positions_counts_new_symbols_only` (`max_positions=1`, `open_positions=1`: `holding=True` → None; `holding=False` → `"plan: max positions"`).
  - `test_versions_source_follows_time` (v1 at 09:00, v2 at 11:00 → 10:00 gets v1, 11:30 gets v2, 08:00 None).
  - `test_size_intents_never_blocks_a_closing_intent_and_scales_risk`: build a `Portfolio` holding 10 TCS long; plan allows nothing; a SELL intent from the holder strategy still yields an order; with plan allowing `orb_breakout` on INFY at multiplier 0.5, the INFY BUY order quantity is half (±1 share) of the same call with `plan=None`. Use the existing `size_intents` test helpers in `backend/tests/test_runner*.py` for context/strategy fixtures.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_plan_gate.py -q -p no:cacheprovider` — FAIL.
- [ ] **Step 3: Implement** gate, runner and backtest wiring.
- [ ] **Step 4: Run the full suite** — PASS.
- [ ] **Step 5: Commit** `feat(engine): game plan gate in size_intents (tightens only) [skip ci]`

---

### Task 4: Builder and prompt

**Files:**
- Create: `backend/plan/builder.py`, `backend/prompts/game_plan.md`
- Test: `backend/tests/test_plan_builder.py`

**Interfaces:**
- Consumes: Tasks 1–2; `backend.learning.library.catalog`; `backend.datalayer.catalysts.catalyst_map`; `backend.datalayer.news_sources.nifty200_sectors`; `backend.datalayer.prices.priority_symbols`; `backend.ai.sentiment.get_cached_sentiment`; Redis `market:regime`, `market:brief`, `market:flows`; `backend.datalayer.market.upcoming`; `backend.llm.llm_service`; `PrefsStore`.
- Produces:
  - `async def build_plan(db, redis, user_id: str, now: datetime, complete=None) -> dict` — `complete(system, prompt) -> str` defaults to `llm_service.get_completion(prompt, system_prompt=system, tier="deep")`. Returns the saved doc.
  - `def intraday_strategies() -> set[str]` (INTRADAY names from `library._strategies()`)

Flow: universe = prefs `universe` (bare symbols); candidates = universe ∪ held/watched (`priority_symbols`) ∪ up to **30** Nifty 200 names from today's `catalyst_map`, ordered by |direction|; for each candidate: sentiment (`get_cached_sentiment`), catalyst direction, sector; context = INTRADAY cards (name, card, backtest passed, paper passed, learned, stats.all) as compact JSON, regime label/score/drivers, brief text (≤ 1500 chars), flows, calendar next 8h, user caps. If `reserve_call` is False → save `fallback_plan(..., "daily AI plan budget used up")`. Call `complete`; on in-band error or `ValueError` from `validate`, retry once, then save fallback with the reason. Otherwise save `validate(..., trigger="pre_open")`.

Prompt `game_plan.md` placeholders: `now, regime, brief, flows, calendar, strategies, candidates, caps`. System: "You plan one trader's intraday session on NSE. You only choose among the strategies and stocks given; you never invent either. Reply with one JSON object only." Body states the JSON schema (fields of `TradePlan` minus `trigger`/`exits`), that `risk_multiplier` ≤ 1 and `skip_day` are for genuinely hostile days, that each `allow` strategy must suit the stock's situation per its card, and that `rationale` is 2–5 short lines a trader reads at 08:50.

- [ ] **Step 1: Write failing tests** (mongomock + FakeRedis; seed `prefs` universe `["TCS","INFY"]`, `market:regime`):
  - `test_builds_validates_and_stores_a_pre_open_plan`: fake `complete` returns `{"allow":[{"symbol":"TCS","strategies":["orb_breakout"]}],"risk_multiplier":0.5,"rationale":["x","y"]}` → saved doc version 1, trigger `pre_open`, multiplier 0.5; the prompt passed to `complete` contains `"orb_breakout"` and `"TCS"`.
  - `test_llm_error_twice_stores_the_fallback`: `complete` returns `"Error generating response: 500"` → trigger `fallback`, both symbols allowed, `complete` called 2 times.
  - `test_budget_exhausted_skips_the_call`: cap 0 → `complete` never called, trigger `fallback`.
  - `test_news_names_join_the_candidates`: a material overnight `news_items` doc on `AXISBANK` → prompt contains `AXISBANK`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** builder and prompt.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(plan): pre-open game plan builder [skip ci]`

---

### Task 5: Pre-open trigger and run-start wiring

**Files:**
- Modify: `backend/engine/autorun.py` (new `PLAN_AT = time(8, 45)`, `async def _preopen_plans(db, redis, now) -> list[str]`, called from `tick` before the start logic; `_may_start` refuses INTRADAY when today's plan has `skip_day`)
- Modify: `backend/routers/trading.py::_launch_run` (INTRADAY: read `store.current`; `symbols += plan.add_symbols`; catalysts = `catalyst_map` merged with plan `allow[].catalyst` directions (plan wins); pass `plan=PlanGate(redis_source(db.redis, user_id))` to `run()`)
- Test: `backend/tests/test_autorun.py` (append), `backend/tests/test_plan_gate.py` (append)

**Interfaces:**
- Consumes: `build_plan` (Task 4), `store.current` (Task 2), `PlanGate`/`redis_source` (Task 3).

`_preopen_plans`: only weekdays with IST time in `[08:45, 09:15)`; users with `auto_paper_intraday` on; per user `SET plan:build:{user}:{date} NX EX 3600` before building, skip if a plan already exists; exceptions logged per user, never raised.

- [ ] **Step 1: Write failing tests**
  - `test_preopen_builds_one_plan_per_user_even_with_two_ticks`: two `tick` calls at 08:46 IST with a stub `build_plan` → called once per enabled user.
  - `test_no_plan_outside_the_window`: 08:30 and 09:20 → not called.
  - `test_skip_day_plan_keeps_the_auto_run_from_starting`: plan with `skip_day` → `_may_start(..., "INTRADAY", ...)` False; LONGTERM unaffected.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** autorun hook and `_launch_run` wiring.
- [ ] **Step 4: Run the full suite** — PASS.
- [ ] **Step 5: Commit** `feat(plan): build plans at 08:45 and run them from the open [skip ci]`

---

### Task 6: Nightly replay scorecard

**Files:**
- Create: `backend/plan/replay.py`
- Modify: `backend/scheduler.py::run_daily_jobs` (call `replay_all` after `_learn`, wrapped in try/except, result key `"plan_replays"`)
- Test: `backend/tests/test_plan_replay.py`

**Interfaces:**
- Consumes: `versions` (Task 2), `PlanGate`/`versions_source` (Task 3), `run_backtest(..., plan=...)` (Task 3), `build_default_strategies`, `catalyst_map`, `nifty200_sectors`, `bars.prev_closes`, `InstrumentMaster`.
- Produces:
  - `async def replay_day(db, provider, user_id: str, day: date) -> Optional[dict]` — None when the user had no INTRADAY run that day (`runs` collection, `mode == "INTRADAY"`, created that IST day) or no plan versions, or no bars. Universe = the run's `universe`. Strategies built twice from `build_default_strategies` (INTRADAY only, same catalysts/sector_of/prev_closes). A: `plan=PlanGate(versions_source(versions))`; B: `plan=None`. Window: `day` 09:15–15:30 IST. Stores and returns `{user_id, date, a: SIDE, b: SIDE, at}` in `plan_scorecards` (upsert on user_id+date), `SIDE = {"net": total_pnl, "max_drawdown", "trades": total_trades, "win_rate"}`.
  - `async def replay_all(db, provider, now: datetime) -> int` (count replayed).
  - `async def weeks_beating(db, user_id: str, now: datetime) -> int` — consecutive ISO weeks, newest first, where Σ a.net > Σ b.net and max a.max_drawdown ≤ max b.max_drawdown.

- [ ] **Step 1: Write failing tests** (stub provider yielding fixed 5-minute bars, e.g. reuse the ORB breakout fixture shape):
  - `test_replay_scores_plan_and_baseline_on_the_same_bars`: plan v1 allows nothing → `a.trades == 0`, `b.trades >= 1`; doc stored.
  - `test_replay_skips_users_without_a_run_or_bars` → None, nothing stored.
  - `test_weeks_beating_counts_consecutive_weeks`: seed 3 weeks A>B then 1 week A<B older → 3.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** replay and scheduler hook (provider: `YFinanceProvider()` as `retune._main` uses).
- [ ] **Step 4: Run the full suite** — PASS.
- [ ] **Step 5: Commit** `feat(plan): nightly replay of plan vs no plan [skip ci]`

---

### Task 7: Docs, deploy, verify

**Files:**
- Modify: `docs/ROADMAP.md` (15.2 done), `docs/ARCHITECTURE.md` (game plan paragraph next to the strategy library), spec "As built" (the six decisions above), `.claude/CLAUDE.md` invariants (one line: the game plan may only tighten; see spec)

- [ ] **Step 1: Edit docs.**
- [ ] **Step 2: Full suite** — PASS.
- [ ] **Step 3: Commit + push** `docs: phase 15.2 game plan core landed [skip ci]`.
- [ ] **Step 4: Deploy** (`git pull --ff-only` in the deploy clone; `docker compose build backend ingest && docker compose up -d backend ingest`).
- [ ] **Step 5: Verify**: backend logs clean after start; `docker exec neotrade-backend python -c` running `build_plan` for one real auto-intraday user with the real LLM → a stored `trade_plans` doc (trigger `pre_open` or `fallback` with a reason) and Redis `plan:<user>:<date>` present; then delete that test doc and key so tomorrow's 08:45 builds fresh.
