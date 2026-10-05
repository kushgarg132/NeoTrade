# Game Plan Revisions, Exits and Mid-Session Adds Implementation Plan (Phase 15.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** During the session the game plan is revised when something material happens (news on a planned or held name or its sector, a regime flip, a high-impact event passing); a revision can close positions and add stocks in play, which the running engine picks up on its next bar.

**Architecture:** A new ingest loop (`backend/plan/revise.py`, 60 s, leader-only) detects triggers, applies the per-user limits, and makes one `deep` call that returns the full updated plan, validated and stored as a new version. The engine already reads the current plan every bar (`PlanGate.refresh`); when the version changes, `run()` closes the plan's `exits` (paper positions; live ones only shadow-logged) and calls an `expand` hook that subscribes the feed to `add_symbols`, backfills today's bars where the feed won't, and extends the strategies' universes.

**Tech Stack:** Python 3.11, Motor/MongoDB, Redis, pytest (asyncio auto), mongomock_motor, existing `FakeRedis`.

**Spec:** `docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md` (section 2 "Revisions", section 3 "Plan exits" and "Adding symbols mid-session", plus both "As built" notes)

## Global Constraints

- Revisions: ≤ **6** per user per day, ≥ **15 min** apart (from the latest version's `at`), only while `in_session(now)`.
- Triggers: a material scored item on a planned/held symbol or its sector; a `market:regime` label change; a high-impact calendar event passing (its time + 5 min).
- Every revision call goes through `store.reserve_call` (`PLAN_LLM_CALLS_PER_DAY`).
- The plan still only tightens versus today's behaviour; exits close **paper** engine positions only. A position whose holding strategy routes live is **shadow-logged** to `autopilot_shadow` (`source: "plan"`), never sent.
- Fallback plans are never revised (the model was unavailable or the budget spent).
- `add_symbols` stay Nifty 200, ≤ 10 per plan (validator).
- No prompt inline in `.py`; prompts in `backend/prompts/`.
- Tests: `cd /home/ubuntu/projects/NeoTrade && python3 -m pytest backend/tests -q -p no:cacheprovider`. Deploy: direct (`[skip ci]`, rebuild `backend ingest`).

## Decisions this plan makes

- A revision returns the **full** updated plan (not a diff); validated with the pre-open universe = `scope − add_symbols` of the current version.
- Triggers that arrive while a user is rate-limited are **dropped**, not queued (the next revision sees the then-current market anyway).
- Feed `add()` exists for `CandlePollingFeed` (per-instrument first poll = warmup catch-up, no separate backfill) and `KiteTickerFeed` (socket subscribe; needs a backfill). `UpstoxMarketFeed` has no `add()` yet (instrument keys are resolved inside its adapter): plan adds are logged and skipped on Upstox runs.
- Backfilled bars go only into the strategy context (history), never through `on_bar`, so no signal fires on a stale bar.
- Version race (15.2 review M5): pre-open builds stop at 09:15 and revisions start at 09:15 in one leader process, so they cannot overlap; no unique index added.

## Review Focus

1. A plan exit for a symbol with no open position, or the same exit listed again in the next version → no order, no error. Pinned in Task 2.
2. A revision whose reply drops a previously added symbol → feed keeps it, gate blocks new entries on it, existing position untouched. Pinned in Task 2.
3. Redis `market:regime` missing (ingest restart) → no regime-flip trigger, no crash; the first label seen is only recorded. Pinned in Task 4.
4. Two material items for the same user in one pass → one revision, both items described. Pinned in Task 4.
5. `expand` raising (instrument unresolvable, feed error) → run continues without that symbol. Pinned in Task 2.

---

### Task 1: Strategies and feeds can grow mid-run

**Files:**
- Modify: `backend/strategies/base.py` (`TokenResolvingStrategy.extend_universe`), `backend/data/feeds/candle_poll.py` (`add`), `backend/data/feeds/live_kite.py` (`add`)
- Test: `backend/tests/test_mid_session_adds.py`

**Interfaces:**
- Produces:
  - `TokenResolvingStrategy.extend_universe(self, symbols: list[str]) -> None` — appends unseen symbols to `self._universe` and `self.spec.universe` (same order, no duplicates). `symbol_for_token` is the run's shared dict, mutated by the caller.
  - `CandlePollingFeed.add(self, instruments: list[Instrument]) -> bool` — appends unseen instruments and updates `self.symbol_for_token`; their first poll yields today's candles with `warmup=True` on all but the newest. Returns `False` ("no backfill needed").
  - `KiteTickerFeed.add(self, instruments: list[Instrument]) -> bool` — extends `self._tokens`; if connected (`self._kws` set in `__aiter__`), calls `subscribe(new)` and `set_mode(MODE_FULL, new)`. Returns `True` ("caller must backfill").

- [ ] **Step 1: Write failing tests**
  - `test_extend_universe_adds_once`: `ORBStrategy(["TCS"], {})`; extend with `["INFY","TCS"]` → `spec.universe == ["TCS","INFY"]`.
  - `test_polling_feed_catches_an_added_instrument_up_as_warmup`: stub provider with 3 closed candles today for INFY; feed started with TCS, first pass consumed, then `add([INFY])` → next pass yields 3 INFY bars with `warmup` `[True, True, False]`; returns `False`.
  - `test_kite_feed_subscribes_added_tokens`: fake kws recording calls; after `__aiter__` started, `add([instr token 9])` → `subscribe([9])`, `set_mode(MODE_FULL, [9])`; returns `True`.
- [ ] **Step 2: Run** `python3 -m pytest backend/tests/test_mid_session_adds.py -q -p no:cacheprovider` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(engine): strategies and feeds can take new symbols mid-run [skip ci]`

---

### Task 2: The runner acts on plan versions (exits, adds)

**Files:**
- Modify: `backend/plan/gate.py` (expose `version: Optional[int]`, `adds: list[str]`, `exits: list[dict]` from the current plan), `backend/engine/runner.py` (`run(..., expand=None, live_holders: Optional[set[str]] = None, shadow_exit=None)`)
- Test: `backend/tests/test_plan_runner.py`

**Interfaces:**
- Consumes: `PlanGate` (15.2), `extend_universe` (Task 1).
- Produces (runner params):
  - `expand: Callable[[list[str]], Awaitable[list[Bar]]]` — given new symbols, makes them tradable and returns backfill bars (already mapped in `symbol_for_token`).
  - `live_holders: set[str]` — strategy names that route live in this run.
  - `shadow_exit: Callable[[str, float, str], Awaitable[None]]` — `(symbol, quantity, reason)` for a live-held position the plan would close.

Behaviour, after `plan.refresh(bar.timestamp)` when `plan.version` differs from the last version this run acted on:
1. **Adds:** `new = [s for s in plan.adds if s not in known_symbols]`; if any and `expand`: `bars = await expand(new)` inside try/except (log, continue); `ctx.update(b)` for each backfill bar; recompute `owner_by_symbol` from strategies.
2. **Exits:** for each `exits` entry whose symbol has a non-zero position in `portfolio`: if `holders.get(symbol) in live_holders` → `await shadow_exit(symbol, qty, reason)`; else emit a MARKET MIS closing order (same shape as `_square_off_orders`, `strategy_name` = holder) appended to this bar's orders. Each (version, symbol) handled once.

- [ ] **Step 1: Write failing tests** (drive `run()` with a list feed, `SimpleStrategyContext`, `SimulatedExecutionClient`, `Portfolio`, a `PlanGate` over an in-memory source whose plan changes at bar 3):
  - `test_plan_exit_closes_a_paper_position_once`: position TCS +10 opened before; v2 exits TCS → one SELL 10 order executed; v2 seen again on later bars → no second order.
  - `test_plan_exit_for_a_flat_symbol_does_nothing`.
  - `test_plan_exit_on_a_live_position_is_only_shadowed`: holder `orb_breakout` in `live_holders` → `shadow_exit` called with `("TCS", 10, reason)`, no order.
  - `test_added_symbol_is_expanded_once_and_backfilled`: v2 adds INFY → `expand(["INFY"])` called once; its returned bars visible in `ctx.history("INFY", 5)`.
  - `test_dropped_add_keeps_streaming_but_opens_nothing`: v3 omits INFY → `expand` not called again; an INFY opening intent is blocked by the gate.
  - `test_expand_error_is_logged_and_the_run_continues`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite** — PASS.
- [ ] **Step 5: Commit** `feat(engine): act on plan revisions -- exits and stocks in play [skip ci]`

---

### Task 3: `_launch_run` wires expand and live-exit shadowing

**Files:**
- Modify: `backend/routers/trading.py::_launch_run`
- Test: `backend/tests/test_plan_runner.py` (append, unit-test the factory)

**Interfaces:**
- Produces: `def make_expand(master, feed, provider, strategies, symbol_for_token: dict[int, str], today: date) -> Callable[[list[str]], Awaitable[list[Bar]]]` (module-level in `backend/plan/expand.py`): resolves `NSE` instruments; adds to `symbol_for_token`; `needs_backfill = await feed.add(instruments)` if the feed has `add` (else logs "feed cannot add symbols" and returns `[]` without extending); extends every INTRADAY strategy; if `needs_backfill`, returns today's closed 5m candles from `provider.history(i, interval="5m", period="5d")` as `Bar(warmup=True)`.
- `_launch_run` passes `expand=make_expand(master, feed, YFinanceProvider(), strategies, symbol_for_token, today)`, `live_holders=set(live_by_strategy)`, `shadow_exit=` a coroutine inserting `{user_id, at, side, symbol, quantity, product: "MIS", source: "plan", reason}` into `autopilot_shadow`.

- [ ] **Step 1: Write failing tests**: `test_make_expand_on_a_polling_feed_needs_no_backfill` (returns `[]`, strategy universes extended, token mapped); `test_make_expand_on_a_ticker_feed_backfills_today_only` (stub provider with yesterday + today candles → only today's, all `warmup=True`); `test_make_expand_on_a_feed_without_add_changes_nothing`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `backend/plan/expand.py` and the `_launch_run` wiring.
- [ ] **Step 4: Run the full suite** — PASS.
- [ ] **Step 5: Commit** `feat(plan): runs subscribe to the plan's new names; live exits are shadow-only [skip ci]`

---

### Task 4: Revision triggers, limits and the revision call

**Files:**
- Create: `backend/plan/revise.py`, `backend/prompts/game_plan_revision.md`
- Modify: `backend/datalayer/worker.py` (`Loop("plan_revise", 60, revise.loop)`), `backend/tests/test_llm_call_tiers.py`, `backend/tests/test_prompts.py`
- Test: `backend/tests/test_plan_revise.py`

**Interfaces:**
- Consumes: `store.current/versions/save/reserve_call`, `validate`, `builder.intraday_strategies`, `builder._held_and_watched`, `reactor._claim`, `news_sources.nifty200_sectors`, `market.upcoming`, `autorun.in_session`.
- Produces:
  - `MAX_REVISIONS = 6`, `MIN_GAP = timedelta(minutes=15)`, `REGIME_SEEN = "plan:regime_seen"`, `EVENT_KEY = "plan:event:{}"`
  - `async def triggers(db, redis, plans: dict[str, dict], now) -> dict[str, list[str]]` — user_id → trigger descriptions (first one's code becomes the version's `trigger`: `news:<item_id>`, `regime_flip`, `event_passed`).
  - `async def may_revise(db, user_id: str, day: date, now) -> bool`
  - `async def revise_plan(db, redis, user_id: str, plan: dict, reasons: list[str], now, complete=None) -> Optional[dict]` — None when budget spent or the reply is unusable (current plan stands; no fallback written).
  - `async def loop(db, redis, now: Optional[datetime] = None) -> int` (revisions made).

Trigger rules: news = `reactor._claim(db, "planned_at", now)` items; an item hits a user when any `type=="symbol"` impact target is in the plan's `scope` ∪ the user's held symbols, or any `type=="sector"` target is the sector of one of those. Regime = `market:regime` label vs `REGIME_SEEN` (missing label → nothing; first label → just recorded). Event = `econ_calendar` `impact=="High"` with `at` in `[now−15 min, now−5 min]`, claimed once via `SET EVENT_KEY NX EX 86400`; it triggers every planned user.

Prompt `game_plan_revision.md` placeholders: `now, trigger, plan, positions, regime, candidates, strategies`. It asks for the **full** plan JSON (same schema as `game_plan.md` plus `"exits": [{"symbol","reason"}]`), states exits only for names currently held, and that unchanged fields should be repeated.

- [ ] **Step 1: Write failing tests** (mongomock + FakeRedis; plans stored with `store.save`):
  - `test_material_news_on_a_planned_name_triggers_once_per_user` (two items, one user → one entry with two reasons).
  - `test_sector_news_reaches_names_in_that_sector`.
  - `test_regime_flip_triggers_and_first_label_only_records` (no label → `{}`; first `neutral` → `{}`; then `risk_off` → every user).
  - `test_passed_event_triggers_once`.
  - `test_limits_cap_and_gap` (6 revisions today → False; last version 10 min ago → False; pre_open only and 20 min ago → True).
  - `test_revise_plan_stores_a_new_version_with_exits`: fake complete returns plan with `exits:[{"symbol":"TCS","reason":"guidance cut"}]` → version 2, trigger `news:n1`, exits kept.
  - `test_unusable_reply_keeps_the_current_plan` (returns None, still 1 version).
  - `test_loop_skips_fallback_plans_and_outside_session`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** revise.py, prompt, worker loop, registry tests.
- [ ] **Step 4: Run the full suite** — PASS.
- [ ] **Step 5: Commit** `feat(plan): event-driven plan revisions during the session [skip ci]`

---

### Task 5: Docs, deploy, verify

- [ ] **Step 1:** ROADMAP (15.3 done), ARCHITECTURE (revisions, exits, adds), spec "As built (15.3)" with this plan's decisions.
- [ ] **Step 2:** Full suite — PASS.
- [ ] **Step 3:** Commit + push `docs: phase 15.3 plan revisions landed [skip ci]`.
- [ ] **Step 4:** Deploy (`git pull --ff-only`; `docker compose build backend ingest && docker compose up -d backend ingest`).
- [ ] **Step 5:** Verify: ingest log lists 15 loops including `plan_revise`; its heartbeat appears in `ingest:heartbeat:plan_revise`; backend start clean.
