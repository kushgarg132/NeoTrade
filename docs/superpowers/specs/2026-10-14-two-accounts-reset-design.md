# NeoTrade reset: two accounts, one daily answer

## Context

Owner says the app is useless and confusing. Scans (frontend IA, backend flows, live prod) confirm why:

- **The app is built around the wrong model.** PRODUCT.md frames it as a "discipline journal" with three money books (Mine, AI, Practice). Owner's actual model: **AI account (Kite) is run by the app; Mine (Upstox) gets recommendations; the two compete.** Practice is a third book with five writers (engine, paper approvals, factor portfolio, paper autopilot, chat) that leaks into AI and Mine screens.
- **Nothing reads his real holdings** except Mine → Holdings, chat and the Friday review. The scan, autopilot fence, game plan, and news alerts all treat *paper* positions as "held". News moving his real stocks never alerts him.
- **No daily answer.** Today shows only *closed* P&L (₹0 on a hold-only day), no holdings value, nothing about his stocks. Portfolio review is manual or Fridays. Morning Telegram lists only pending proposals. Getting "how am I doing, what to do" takes 5–7 taps across 3 tabs.
- **It mostly isn't running.** No broker session on 10-13 and 10-14 → no intraday, no plan, no journal import, holdings frozen at 10-09. Kite dies 06:00 IST daily and nobody nudges a re-login.
- **AI tiers broken.** Ingest LLM success 7–16%: `agy/gemini-3.7-flash-low` not in catalog, `codex/gpt-5.5` rejected since 14:59 today; `news_process` crashes hourly (`components/analyst/agent.py:80`, list has no `.find`).
- **Money bug.** `suggestions/exits.py` re-sold BHEL 10× on 10-13, doubling each time; paper ledger now holds BHEL −20,480 (₹8.8M short on a ₹25k book). Can recur on next stop breach.
- **Feedback loop broken.** Autopilot paper trades tagged `autopilot:*` (`autopilot/service.py:203`) so the gate/learning (`risk/paper_gate.py:45`, `learning/adapt.py:117`) never credit the originating strategy → nothing can ever become "proven".
- **121 proposals in 7 days, 107 expired, 0 declined/approved status.** Idea firehose nobody acts on.

## Decisions (owner, 2026-10-14)

| Question | Answer |
|---|---|
| Trading styles | Long-term holdings, swing, intraday |
| AI account | Run by the app. **Paper until a strategy passes the gate**, then live on capped capital |
| Mine | App recommends; owner places (or one-tap live approve, already built) |
| Paper / Practice | Becomes the AI account's paper mode. AI vs Mine contest stays |
| Recs for Mine | **Only from strategies proven on the AI account**, plus holdings verdicts |
| Rec types for Mine | Holdings hold/add/trim/sell · swing ideas · exit alerts on his positions. **No intraday alerts for Mine** (intraday is AI-only) |
| Delivery | In-app Today · Telegram pre-market · Telegram post-close |
| Cuts | Propose list, owner approves |

## Target model

```
           ┌──────────── AI account (Kite) ────────────┐
ideas ───► │ intraday engine · swing/long-term scan ·   │ paper ─(gate passed)─► live, capped
           │ news · autopilot  →  ONE AI book           │
           └───────────────┬───────────────────────────┘
                           │ per-strategy record (net of charges)
                           ▼
              proven strategies only
                           │
           ┌───────────────▼─────── Mine (Upstox) ─────┐
           │ swing ideas · holdings verdicts ·          │ owner places / one-tap
           │ exit alerts on real positions              │
           └────────────────────────────────────────────┘
                 Scoreboard: AI vs Mine, daily
```

## Navigation (5 tabs → 4)

| Tab | Answers | Contents |
|---|---|---|
| **Today** | Where am I, what do I do | Login strip · **Portfolio pulse** (value, day change, unrealised, top movers + why) · **Do today** (holdings verdict changes, proven swing ideas, exit alerts, logins) · Scoreboard AI vs Mine · market backdrop |
| **Mine** | My account | Holdings (verdicts default tab, live prices) · Ideas for me (proven swing recs, approve/decline) · Trades & habits (journal) |
| **AI** | What the AI is doing | Account (paper/live, capital, P&L, open positions) · Activity (orders, refusals, Stop) · Strategies (record, gate progress, builder) · Settings (autopilot, limits) |
| **Research** | Look something up | Stock search/analysis · News (with "my holdings" filter) · Watchlist |
| More (in header) | — | Settings: brokers, Telegram, safety, AI model |

Practice tab, `/practice/*`, separate Decisions page gone (redirects). One name per thing: "Idea" (not proposal/suggestion/decision), "Waiting" for chat cards, "Loss stop" for the daily limit, net of charges everywhere.

## Phases

Each phase ships and deploys on its own; order is by value per effort.

### Phase A — Stop the bleeding (1 session)
1. **BHEL doubling**: root-cause in ledger matching (see design notes), fix at shared ledger path, add regression test. Clean prod paper book (back up `paper_*` first; owner confirms reset vs repair).
2. **LLM tiers**: point standard tier at a model present in OmniRoute catalog; deep tier off `codex/gpt-5.5`. Fix `_extract_json` to accept list content (`components/analyst/agent.py:80`). Verify ingest success rate > 90%.
3. **Daily login nudge**: 08:30 IST Telegram with one-tap Kite + Upstox login links when sessions are missing; Today strip already shows it. Re-check at 09:10.
4. **Holdings without a session**: reprice last snapshot from ingest quotes / `daily_bars` so Today and Holdings never freeze at a 5-day-old value; mark "as of".

### Phase B — Real holdings are "held" (1 session)
1. One helper `my_holdings(user_id)` = latest `portfolio_snapshots` scoped to role `mine`.
2. Use it in: news reactor held audience (`datalayer/reactor.py:116`), scan `held` for Mine-facing ideas (`suggestions/scan.py:160`), live-approve concentration/already-held check (`routers/suggestions.py:302`).
3. `refresh_portfolio` reviews per account; AI text covers Mine only (`portfolio/service.py:121`).
4. Daily (not Friday) holdings review in the 16:00 pass, `analyse=True` for Mine; verdict-worsened alert daily.

### Phase C — One AI book (1–2 sessions)
Per design notes below: AI paper and live trades in one AI ledger, every trade keeps `strategy` = origin + `via` (engine/autopilot/news/approval); gate and learning credit origin. Paper approvals for Mine-ideas no longer write a paper book (owner trades them for real). Factor portfolio and paper chat orders: cut (see Cuts). Exits managed for AI live engine orders and AI live approvals.

### Phase D — Proven-only ideas for Mine (1 session)
1. "Proven" = `risk/paper_gate.py` passes on AI record (reuse, no new rules).
2. Mine → Ideas shows only ideas from proven strategies, max 5, swing/long-term only, with entry/stop/target/hold days and the strategy's AI record line. Until something is proven: empty state "No strategy has earned your money yet — AI is testing N" with gate progress.
3. Exit alerts: for ideas he approved/placed on Mine, watch stop/target against live/ingest quotes, Telegram once per level.

### Phase E — Today + Telegram daily answer (1–2 sessions)
1. `GET /today` adds: portfolio pulse (from B helper + live prices), "Do today" list, scoreboard (AI vs Mine: today, month, all — net).
2. Telegram 08:45 pre-market: login status, holdings with news overnight, ideas pending, AI plan one-liner.
3. Telegram 16:15 post-close: portfolio value/day change, top movers + why (holding headlines), verdict changes, AI vs Mine today, tomorrow's events on held stocks.
4. Redesign Today screen per DESIGN.md tokens (phone first).

### Phase F — Navigation reset + cuts (1–2 sessions)
Apply nav table above; merge pages; redirects; rename concepts; update PRODUCT.md, DESIGN.md nav section, handbook.

## Proposed cuts (owner approves)
- **Practice book & `/practice/*` pages** → folded into AI.
- **Paper approvals by hand + paper order ticket** — would pollute the AI's record; Mine trades for real.
- **Research → Scanner "bullish scan"** (`routers/scanner.py`, `research/scanner.py`) — second scanner, feeds nothing.
- Chat keeps read tools + live-Mine order card + AI controls (paper order path goes with the ticket).
- **Separate Decisions page** — Ideas live under Mine; AI ideas auto-handled by autopilot.
- **Duplicate autopilot activity views** (4 places → AI › Activity + one Today line).
- **Options chain** — Upstox-only read view; owner doesn't trade F&O. Hide (keep code).
- Keep: game plan (feeds AI intraday), strategy builder (feeds AI), journal/habits (Mine), handbook (admin).

## Verification
- Backend: `pytest` (1735 tests baseline) per phase; new regression test for ledger doubling; test that autopilot trade credits origin strategy in gate.
- Frontend: `npm run build` (not just lint).
- Prod checks after each deploy: ingest LLM success rate from logs; `/today` returns pulse with today's date; Telegram 08:45 + 16:15 received; paper ledger has no negative long-only positions; holdings snapshot ≤ 1 day old.
- Deploy mode: ask once before first push (CLAUDE.md).

## Design notes (Phases A, C, D detail)

**BHEL root cause (A1)**, three faults that compound:
1. `suggestions/exits.py:136-141` sells the trade row's qty, never checks the netted position.
2. Engine runner snapshots its whole in-memory portfolio every bar (`engine/runner.py:615`, `engine/persistence.py:58-63`), zeroing BHEL in the shared book while the BUY trade stays OPEN.
3. `_advance_trade` (`persistence.py:119-149`) matches the OPEN trade by symbol and grows it on an opposite-side fill. 20 × 2^10 = 20,480.

Fix in shared paths:
- `fill_on_paper` (`suggestions/service.py:50`) refuses a CNC SELL above the long held.
- `check_exits` sells `min(qty, held)` and closes stale trades. Each trade gets its own try/except.
- `_advance_trade` closes the trade on a sign flip and opens a new one.
- Runner snapshots only the symbols that filled. Grep the `paper_positions` readers first.
- Regression test: flat position + OPEN BUY, run exits twice, expect no fills and the trade closed.

**One AI book (C)**: keep the two existing ledger users. `user_id` = AI paper (today's Practice) and `user_id:autopilot` = AI live (`autopilot/service.py:30,36`). "AI book" = `trades_query` (`:42-44`) without its strategy regex.
- Add `via` to `Order` (`core/models.py`) and store it in `_open_trade` (`persistence.py:171`).
- `AutopilotOrder.strategy` = origin, and `via=autopilot:<source>` (`service.py:53,203`).
- Pass the origin at `engine/execution/autopilot.py:26`, `engine/autorun.py:357` and `service.py:241`.
- Switch the tag filters to `via`: `service.py:44,99-102`, `exits.py:122`, `routers/trading.py:445`. Gate, learning and `_proven_strategies` then credit the origin with no other change.
- Factor portfolio stays as an AI strategy (it already writes this book). It moves off the cut list.
- Delete: human paper approvals (`routers/suggestions.py:147-175`, `chat/actions.py:473`), the paper ticket (`engine/paper_orders.py`, `routers/orders.py`), and the fence's `others` / "Practice already holds" refusal (`fence.py:81-82`). Delete their tests too.
- Prod: `mongodump`, then reset the `paper_*` docs where `user_id == <user>` (20 trades, already corrupt). Backfill `via` on the `:autopilot` docs.

**Mine's ledger and exit alerts (C/D)**: `approve-live` books to `user_id:mine` instead of the AI paper book. Reconcile already honours `ledger_user` (`engine/reconcile.py:50`). `exits.check_exits` turns into alerts only for Mine: open `:mine` trades that are still in `mine_holdings` go through `exit_reasons`, then `notify`. A trade whose symbol is gone from his holdings is closed.

**AI live exits (C)**: `autopilot.check_exits` also sweeps OPEN live INTRADAY trades at square-off time (~5 lines). It runs whenever open trades exist, not only when autopilot is on, which fixes the stranding on off. Strategy-level live stops wait until a strategy actually goes live.

**`mine_holdings` helper (B)**: in `portfolio/service.py`, next to `latest_snapshot` (`:250`). It reads `raw_holdings` filtered to the brokers with role `mine`. It is used by scan `held` (`scan.py:160`, so SELL ideas cover only real holdings), the reactor audience (`reactor.py:116`) and the review scorecard (`service.py:150`). The plan builder and the fence stay on the AI book.

**Proven feed (D)**:
- Move `_proven_strategies` (`autorun.py:377`) into `risk/paper_gate.py`.
- The autopilot no longer consumes proposals: `$set ai_order` replaces `decide(EXECUTED)` (`autorun.py:360`). AI and Mine then see the same idea. The autopilot skips docs that have `ai_order`.
- Filter Mine to proven ideas in three places: the morning notify (`autorun.py:325`), `list_suggestions` (`routers/suggestions.py:130`), and a 409 guard on `approve-live`, which is the trust boundary.
- Audit every "PENDING means untouched" assumption: chat approve, `expire_stale`.

## Expectation to set with owner
**Mine's idea list starts empty and stays empty for weeks.** A strategy has to earn it with 20 days and 30 trades that pass the gate, and swing strategies trade rarely. Holdings verdicts, exit alerts and the daily pulse work from day one. The AI vs Mine scoreboard will now include the engine and factor trades, which is intended.

## Risks
- `mine_holdings` is only as fresh as the last snapshot (A4 + daily review mitigate). Exit alerts on a sold position are closed out by the stale-close logic.
- The runner snapshot change may affect readers of the live marks. Grep before changing it.
- Removing paper approvals and the ticket is a visible feature loss. It is on the cut list for the owner to confirm.
