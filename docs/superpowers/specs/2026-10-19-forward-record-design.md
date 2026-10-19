# Forward record (Phase 21 step 4): design

Date: 2026-10-19. Status: approved in chat, awaiting spec review.
Source: `docs/ROADMAP.md` Phase 21 step 4 ("paper-trade and score every rule candidate before
outcome; compare net returns and calibration to NIFTY. An unproven result stays labelled
unproven"), and the Phase 21 done-when line ("every AI/ML/RL claim links to a stored forward record").

## Decisions (2026-10-19)

- One record for four sources: Picks, engine strategy entries, LONGTERM suggestions, news proposals.
- A common "proven" rule labels every source. It does NOT gate money: the paper gate
  (`risk/paper_gate.py`), Picks `live_refusal` and the proven news themes keep deciding; the
  scorecard shows where they disagree with the rule.
- Every candidate counts whether or not anyone acted on it.
- No backfill: scoring starts with candidates decided after deploy.

## Today

| Source | Stored before outcome | Scored vs NIFTY | Calibration | Proven rule |
|---|---|---|---|---|
| Picks (`picks`) | yes | yes, net | `forecast/picks.py::forward` | `live_refusal`: 100 scored + gap ≤ 0.05 |
| Engine (`paper_trades`) | as fills | no | no | paper gate |
| LONGTERM suggestions (`suggestions`) | yes | no | no | strategy's paper gate |
| News (`news_outcomes`) | yes | price move vs benchmark | no | themes n ≥ 20, weight > 1 |

## Design

### Records: `backend/forward/store.py`

- Collection `forward_records`, `_id = "<source>:<name>:<symbol>:<YYYY-MM-DD>:<side>"` (insert
  once; a duplicate insert is ignored, so a re-derived signal the same day is one record).
- Fields: `source` (`picks` | `engine` | `suggestion` | `news`), `name` (setup, strategy or news
  theme; `"unknown"` when absent), `user_id` (`"system"` for Picks), `symbol`, `side`
  (`BUY` | `SELL`), `decided_at` (UTC), `intraday` (bool), `ref_price` (price at decision, may be
  None), `horizon_days` (int, 0 = same day), `predicted` (optional `{p_up, median}`), `outcome`
  (None until scored), `scored_at`.
- Indexes: `(outcome, decided_at)`, `(source, name)`.
- `ForwardStore(db)`: `async record(**fields) -> bool` (never raises; logs a warning),
  `async due(now) -> list[dict]`, `async set_outcome(id, outcome)`, `async list(source=None, name=None, limit=200)`.

### Writers (best effort)

| Source | Where | name | horizon_days | predicted |
|---|---|---|---|---|
| Picks | `forecast/picks.py::run`, beside the `picks` insert | setup | setup horizon | `p_up`, `expected.median` |
| Engine | `engine/runner.py::size_intents`, INTRADAY entries that pass sizing, only when a `forward` recorder is passed in; paper/AI run launchers pass it, backtests and scans never do | strategy | 0 | none |
| Suggestion | `suggestions/sink.py::SuggestionSink.__call__` after `store.create`, `source != "news"` | strategy | `max_hold_days` from the proposal, else 20 | none |
| News | same sink call, `source == "news"` | theme from the proposal, else `"news"` | 5 | none |

LONGTERM and swing entries reach the sink, so the engine writer records INTRADAY entries only
(no double record).

### Scorer: `backend/forward/score.py`, run in the 16:00 daily pass after Picks

- Loads the same daily-bar table Picks uses (`forecast/picks.py::load`), so no extra reads when
  run right after it in the pass.
- For each due record (`outcome` None, decided at least `horizon_days` trading days ago):
  - not intraday: entry = open of the next trading day after `decided_at`, exit = close
    `horizon_days` trading days after entry (`forecast/study.py::outcome` semantics);
  - intraday: entry = `ref_price` (fallback: that day's open), exit = that day's close;
  - SELL records score the short side's return (sign flipped), CNC charges as for BUY.
  - Net via `lab/assumptions.py::round_trip_return` (10 bps, charges); NIFTY return over the same
    entry/exit days. Outcome `{entry_date, exit_date, net, nifty, excess, won}`.
  - Missing symbol or bars: leave unscored; after 10 trading days past due, set
    `outcome = {"void": "no bars"}` so it stops retrying (excluded from stats).

### Scorecard and rule: `backend/forward/scorecard.py`

- Per `(source, name)` over scored, non-void records: `n`, `mean_net`, `mean_excess`, `t`
  (mean_excess / standard error), `hit_rate` (net > 0), `brier` and `calibration_gap`
  (|mean p_up − hit rate|) only where `predicted.p_up` exists.
- `MIN_N = 100`, `MIN_T = 2.0`, `MAX_GAP = 0.05`. Proven = `n >= MIN_N and mean_excess > 0 and t >= MIN_T and (gap is None or gap <= MAX_GAP)`.
- `label`: `"proven"` or `"unproven"` plus `progress = min(n, MIN_N)`.
- `gate`: what the existing gate says for the same name (Picks: `live_refusal(...) is None`;
  engine/suggestion: strategy in `paper_gate.proven_strategies`; news: theme in the proven theme
  weights), and `disagrees = gate != (label == "proven")`.

### API and UI

- `GET /api/v1/forward/scorecard` → rows above; `GET /api/v1/forward/records?source=&name=&limit=`;
  both admin only (`backend/routers/forward.py`).
- Lab › Forward tab (`/lab/forward`, admin): scorecard table (source, name, n/100, mean excess,
  t, hit rate, calibration gap, label, gate, disagreement flag); a row opens its records.
- A shared `ForwardBadge` (Proven / Unproven n/100) on: Picks page (per setup), Lab strategy cards,
  Mine ideas (per strategy), AI overview (per strategy). It reads the scorecard once per page.

## Error handling

- Writers and scorer never raise into their callers; the scorer's failures go to the pass log and
  `job:last:forward` (via `system/jobs.py::mark`).
- An old frontend ignores new fields; the badge hides when the scorecard call fails.

## Testing

- Store: idempotent insert; `record` with Mongo failing returns False.
- Writers: Picks run writes one record per stored pick; sink writes `suggestion` vs `news`; the
  engine writer writes only INTRADAY entries and only when the recorder is passed (a backtest
  run writes none).
- Scorer: next-open entry; horizon crossing a NSE holiday (2026-10-20); intraday same-day;
  SELL sign; missing bars then void after 10 days; NIFTY window equals the record's window.
- Rule: n 99 vs 100; t 1.99 vs 2.0; gap 0.05 vs 0.051; no predictions → gap None passes.
- API admin only; frontend badge and scorecard helpers (`node:test`).

## Docs

`docs/wiki/picks-and-signals.md` (forward records, scorecard), `trading-engine.md` (runner writer),
`data-ai-jobs.md` (16:00 pass step), `platform.md` (endpoints), `frontend.md`; handbook page;
`PRODUCT.md` (proven/unproven label); `docs/ROADMAP.md` step 4 status.

## Out of scope

Changing any gate; backfilling history; ML/RL sources (steps 5-6); options candidates (no
daily-bar outcome for contracts).
