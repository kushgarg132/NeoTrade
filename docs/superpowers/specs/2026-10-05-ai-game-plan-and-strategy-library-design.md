# AI game plan, strategy library, and news across the app

User-approved design, 2026-10-05. Builds on Phase 14 (the market & news data layer).
Four sub-projects, each gets its own implementation plan.

## Intent

Today the intraday run starts every intraday strategy on one fixed universe and lets
the composite score (rule × news sentiment) decide. The goal is an AI that reads the
news layer and **chooses** what runs, per user, per day — which strategies on which
stocks, how much risk, what to exit — while the existing rules still generate, score,
size and gate every order.

Success: over paper trading, the plan-governed day beats the ungoverned baseline on net
P&L after charges with equal or lower drawdown, and nothing becomes less safe than today.

### Decisions (from the brainstorm)

| Question | Decision |
|---|---|
| AI authority | **Chooses, rules execute.** The AI never originates or sizes an order. |
| Plan scope | **Per user.** Each user's plan reuses the shared market read (regime, brief, scored news). |
| In-session | **Event-driven revisions**, capped. |
| Levers | Pick strategies per stock; add stocks in play; tighten risk / skip day; exit on news. |
| Proof | **Side-by-side paper** via a nightly replay (plan vs no plan), weekly scorecard. |
| Approach | **Plan gates a superset run**; one structured LLM call per plan. Tool-using agent loop deferred. |
| Library | Catalog of the existing strategies **plus four new ones**. |

### Invariants (never broken by anything below)

1. The plan can only **remove or shrink** orders. It never loosens a user cap, the
   kill switch, learned rules, the backtest gate, the paper gate, or the autopilot fence.
2. Strategy exits and the 15:15 square-off are never blocked by the plan.
3. A failed, invalid, over-budget or missing plan falls back to today's behaviour
   (everything allowed on the user's universe, multiplier 1).
4. Nothing becomes live because of a plan. Live AI-account news exits stay shadow-only
   until the review required by `2026-10-05-autopilot-news-design.md`.
5. `backend/strategies/` stays I/O-free and wall-clock-free (existing tests enforce it).
6. The plan never touches conviction. `composite.py` stays the only conviction formula
   (`AI_CAP`, `RULE_FLOOR` unchanged); `risk_multiplier` scales sizing after scoring, the
   same place `LearnedRules` acts. New strategies emit `Intent`s with non-empty
   `reason_codes` and are scored like any other.

## 1. Strategy library

### Static card

Each strategy class gains a `CARD` class attribute, a frozen model in
`backend/strategies/card.py`:

| Field | Type | Example (ORB) |
|---|---|---|
| `style` | `breakout \| reversion \| momentum \| options` | `breakout` |
| `regimes` | subset of `risk_on, neutral, risk_off` | `[risk_on, neutral]` |
| `needs` | subset of `gap, volume_spike, range_day, trend_day, catalyst, sector_move` | `[volume_spike]` |
| `best_when` | one sentence | "Clean opening range, volume above average, trending tape." |
| `avoid_when` | one sentence | "Event within the hour, choppy open." |
| `typical_hold_minutes` | int | `90` |

A test asserts every registered strategy has a `CARD`.

### Live card

`backend/strategies/library.py`: `async catalog(db, user_id, mode="INTRADAY") -> list[StrategyCard]`,
the static card plus:

- backtest gate: latest `passed`, profit factor, max drawdown (`BacktestGateStore.latest`);
- this user's paper record and pass/fail (`paper_gate.paper_records`);
- learned state (`learning/adapt.py`): paused, raised floor, regime-off side;
- expectancy by regime and by reason code (`learning/attribution.py`, already shrunk toward zero).

Consumers: the plan builder (section 2); the chat `list_strategies` tool
(`backend/chat/tools.py`), which returns cards instead of names; a Library page that
replaces the Settings promotion table (`GET /settings/strategies/promotion` becomes
`GET /strategies/library`).

### Four new intraday strategies

All follow the existing contract (`TokenResolvingStrategy`, 5-minute bars, `PARAMS`/`GRID`
for retune), are added to `build_default_strategies`, and, like every strategy, paper-trade
until the backtest and paper gates pass.

| Name | Logic | Inputs beyond bars |
|---|---|---|
| `gap_and_go` | Gap ≥ X% on a plan-flagged catalyst; holds above the first 15-min low with volume ≥ Y× average → long (mirror short for negative catalysts). Stop: first 15-min low/high. | `catalysts: {symbol: direction}` injected at construction, like `AnalystVerdictStrategy`'s verdicts. |
| `gap_fill_fade` | Gap ≥ X% with **no** catalyst (or weak), fails to hold the first 15-min extreme → fade toward prior close. Target: prior close. | same `catalysts` map (absence is the signal) |
| `trend_day_pullback` | Price above VWAP, 20-EMA rising, first pullback to 9/20 EMA that holds → long (mirror short). | none |
| `relative_strength_sector` | Stock outperforming its sector index by ≥ Z% since open after a sector move, pulls back and holds → long the leader (mirror: short the laggard). | sector index bars in the feed; `sector_of: {symbol: index}` at construction |

Without a plan (backtests, the baseline replay) `catalysts` is empty: `gap_and_go` stays
silent and `gap_fill_fade` treats every gap as un-catalysed. That is honest for a baseline
and keeps backtests runnable. Backtest gating of these two uses historical scored news
from `news_items` to build the catalyst map per day where it exists. Scored history starts
2026-10-05, so these two stay paper-only (gate not yet passable) until the gate's minimum
window of scored days exists; that is expected, not a bug.

### As built (15.1, 2026-10-05)

- The live catalog lives in `backend/learning/library.py`, not under `backend/strategies/`
  (that package stays I/O-free).
- `relative_strength_sector` is **peer-based**: it compares a stock with its Nifty 200 sector
  peers in the same run. No sector-index feed is added, so section 3's "sector indices in the
  universe" is dropped. Coverage: only Nifty 200 symbols with ≥ 3 sector peers in the run can
  trade (about 32 of the 75 default names); the plan's added Nifty 200 names widen it.
- Live feeds carry only today's bars, so the gap strategies also get the previous close
  per day (`backend/datalayer/bars.py:prev_closes`, from `daily_bars`) at construction.
- Until 15.2's plan exists, live runs get catalysts straight from
  `backend/datalayer/catalysts.py:catalyst_map` (same shape the plan will supply).

## 2. Per-user game plan

### Store

Mongo `trade_plans`, one document per (user, IST date, version):

```
{user_id, date, version, at, trigger,            # "pre_open" | "news:<item_id>" | "regime_flip" | "event_passed" | "fallback"
 skip_day: bool,
 risk_multiplier: float,                          # clamped to [0.25, 1.0]
 max_positions: int,                              # clamped to <= user's cap
 add_symbols: [str],                              # <= 10, Nifty200 only
 allow: [{symbol, strategies: [str], catalyst?: {item_id, direction}}],
 exits: [{symbol, reason}],
 rationale: [str]}                                # 2-5 short lines for UI/Telegram
```

Redis `plan:{user_id}:{date}` holds the current version (JSON, TTL to end of day + 1h)
for per-bar reads.

### Builder (`backend/plan/builder.py`)

Runs at 08:45 IST on weekdays as a step in `autorun.tick`, for every user with
`auto_paper_intraday` on. One `deep` LLM call, prompt `backend/prompts/game_plan.md`,
with pre-computed context:

- the user's live strategy cards (section 1);
- `market:regime`, macro board, FII/DII flows, calendar (next 8h), the latest brief;
- candidates: user universe ∪ held ∪ watched ∪ up to 30 Nifty200 names ranked by material
  news in the last 18h — each with blended sentiment, top 3 scored items, pre-open gap %;
- the user's caps and prefs.

### Validation (`backend/plan/validate.py`, pure)

- drop unknown strategies, non-intraday strategies, unknown or out-of-universe symbols
  (`add_symbols` must be Nifty200);
- clamp `risk_multiplier` to [0.25, 1.0], `max_positions` to ≤ user cap, `add_symbols` to 10;
- an `allow` entry for a symbol not in universe ∪ `add_symbols` is dropped;
- invalid JSON: one retry, then the **fallback plan** (`trigger="fallback"`: every intraday
  strategy on the user's universe, multiplier 1, no adds, no exits).

### Revisions

Triggers, detected by the existing reactor loop (`backend/datalayer/reactor.py`) and a
regime watcher in the same ingest process:

- a material scored item on a held or planned symbol, or its sector;
- `market:regime` label change;
- a high-impact calendar event passing (its time + 5 min).

Limits: ≤ 6 revisions per user per day, ≥ 15 min apart, only during the session. The
revision call (`backend/prompts/game_plan_revision.md`) gets the current plan, open
positions and the trigger and returns a diff (same fields), validated as above and
merged into a new version.

### Budget

`PLAN_LLM_CALLS_PER_DAY` (setting, default 100), counted in Redis
`plan:calls:<IST date>` like `news:deep_calls`. Pre-open plans are reserved first; past the
cap, revisions stop and the current plan stands. Users without a plan get the fallback.

### As built (15.2, 2026-10-05)

- No per-user positions pref exists, so `max_positions` is capped at 10.
- No pre-open gap % (NSE pre-open prices are in no feed here); candidates carry overnight
  catalysts and their headlines instead.
- Pre-open/fallback plans carry no exits; plan exits come with revisions (15.3).
- The replay runs inside the 16:00 daily pass, not at 16:30.
- Live routing is unchanged: the gate filters paper and live alike (it only tightens);
  `weeks_beating` is computed for 15.4 to show, nothing routes on it yet.
- `risk_multiplier` scales equity sizing; option intents are gated but sized as before.
- A manual run on a `skip_day` still starts, and the gate lets it open nothing.
- Plans carry **no catalysts**: only scored news (`catalyst_map`) makes a gap strategy fire, so
  a plan can never create an entry. The `allow[].catalyst` field in section 2 is dropped.
- A `fallback` plan gates nothing, and a plan only judges its `scope` (universe + adds): other
  symbols a run trades (F&O underlyings, a manual custom universe) pass untouched.
- A plan-read error never stops a run: the gate trades without a plan and reads again next bar.
- Runs record `base_universe` and `plan_adds`; the replay's B trades the base universe, A base + adds.

## 3. Engine enforcement

### Run start (`routers/trading.py::_launch_run`)

- Reads the user's current plan (or builds the fallback).
- `skip_day` → the auto-run does not start; Today shows the rationale.
- Universe = user universe ∪ `add_symbols`.
- `build_default_strategies` gains `catalysts` and `sector_of` arguments.

### `PlanGate` (`backend/plan/gate.py`)

Applied in `size_intents` next to `LearnedRules`. Order: kill switch → learned rules →
plan gate → sizing → (AI account) autopilot fence.

- Opening intents: pass only if `(strategy, symbol)` is in `allow`; risk_pct ×
  `risk_multiplier`; refused once open positions ≥ `max_positions`.
- Closing intents: always pass.
- Reads the Redis plan at most once per bar; a missing key means fallback.

### Plan exits

When a new version lists `exits`, the runner closes those positions at the next bar
through the same path as the 15:15 square-off. Engine paper runs: immediate. AI-account
live positions: recorded in `autopilot_shadow`, not sent (invariant 4).

### Adding symbols mid-session

- Feeds gain `add(instruments)`: ticker feeds subscribe on the open socket; polling feeds
  append.
- Before a symbol activates, the runner backfills the day's 5-minute candles from the
  provider so ORB ranges, VWAP and EMAs are correct.
- `TokenResolvingStrategy.extend_universe(symbols, symbol_for_token)` adds it to strategies.

### Nightly replay scorecard (`backend/plan/replay.py`)

At 16:30 IST, for each user who ran: replay the day's 5-minute bars (shared provider)
through `runner.run` with `SimulatedExecutionClient` twice:

- **A**: the day's plan versions applied at their timestamps;
- **B**: no plan (today's behaviour on the user's universe).

Store in `plan_scorecards`: net P&L after charges, max drawdown, trades, hit rate, for A and
B. Weekly roll-up on Today and Telegram. Plan-chosen trades become eligible for live routing
only after **4 consecutive weeks** where A beats B on net P&L with drawdown ≤ B's; until then
live routing is exactly today's.

### As built (15.3, 2026-10-05)

- A revision returns the full plan (not a diff), validated against the pre-open universe.
- Triggers that arrive while a user is rate-limited are dropped, not queued.
- Feed `add()`: candle polling (catch-up as warmup) and Kite (subscribe + backfill into the
  context only, never through `on_bar`). Upstox runs skip plan adds for now.
- Plan exits close paper engine positions with MIS market orders; a position held by a strategy
  routing live is logged to `autopilot_shadow` with `source: "plan"` and never sent.
- Pre-open builds stop at 09:15 and revisions start at 09:15 in one leader process, so plan
  versions cannot race.

## 4. News across the app

Read-only consumers of existing datalayer keys (`sentiment:{SYM}`, `news_items`,
`analyst_verdict:{SYM}`); no new LLM calls.

| Surface | Change |
|---|---|
| Portfolio / MyPortfolio | sentiment chip + latest material headline per holding; holdings with material negative news sort first; rebalance rows cite news |
| Watchlist | sentiment column, "news today" dot linking to the filtered feed |
| Scanner | sentiment + catalyst columns, "catalyst in last 24h" filter |
| Decisions inbox | 1–3 news items behind each proposal's AI score (stored at proposal time for every source) |
| Journal | `news_at_entry` snapshot (sentiment, top item ids) on every opened trade; insights: "traded against strong news", "entered ≤ 15 min after a material item", with win rates |
| AI Activity | **Today's plan** card: rationale, allowed pairs, risk multiplier, revision timeline with triggers, weekly A-vs-B scorecard |
| Library page | strategy cards (section 1) |
| Telegram | pre-open plan summary and each revision, with the existing stop button |

## Build order

1. **Library**: `CARD`s, `library.catalog`, `/strategies/library`, chat tool, the four new
   strategies (each backtest-gated).
2. **Plan core**: store, builder, validation + fallback, `PlanGate`, run-start wiring,
   nightly replay scorecard.
3. **Revisions**: reactor/regime triggers, plan exits, feed `add()` + backfill.
4. **Surfacing**: section 4 UI/API, plan card, library page, Telegram.

## Testing

- `validate`: clamps only tighten; unknown names dropped; invalid → fallback.
- `PlanGate`: drops disallowed opening intents, never closing ones; multiplier applied;
  max_positions enforced; missing plan = fallback.
- Builder: LLM failure and budget exhaustion yield the fallback plan.
- Replay: same bars + same plans → identical results (deterministic).
- New strategies: fixed bar fixtures per signal and non-signal case; existing
  no-I/O / no-`datetime.now` tests cover them.
- Revisions: cap and min-gap respected; only material items on held/planned names trigger.

## Out of scope

- A tool-using agent loop (approach C). The library's card interface makes it a later add-on.
- The AI originating or sizing orders.
- Loosening any cap, gate or fence; enabling live news exits.
- Long-term (CNC) strategy planning; this design is intraday only.
