# News as the backbone: plan

Date: 2026-10-26. Status: proposed, owner decision pending. Evidence comes from prod Mongo,
read-only, the same day.

## The rule that runs through every phase

News gets **power in proportion to its measured accuracy**, and gets it nowhere else.
- Any use that changes what is bought, sold, sized or ranked must first pass the outcomes ledger
  (`datalayer/outcomes.py`), on fresh data, under a stated bar.
- Any use that only explains (context, notes, flags, timelines) can ship now.

This keeps the invariants in `.claude/CLAUDE.md`:
- AI is at most 30% of conviction, and AI sizing weight is 0 until it is validated.
- There is one conviction formula.
- AI cannot rescue a trade the rules did not support.
- Every intent carries reason codes.
- The game plan only tightens.

## Where news stands today (measured)

**Pipeline**
- 2,699 items fetched and 977 scored in the last day; 23,480 fetched in the last 7 days.
- History starts **2026-10-05**, so it is 3 weeks deep.
- 2,778 items are `FAILED` and are never retried.

**Outcomes ledger** (`news_outcomes`)
- 3,987 snapshots, 3,045 with a 5-day result.
- `move_` is the target's return **minus NIFTY's**.

**Direction accuracy** (|direction| >= 0.5):

| scope | 1-day hit | 5-day hit | 5d, impact >= 7 | n (5d) |
|---|---|---|---|---|
| COMPANY | **43%** | **42%** | 48% | 765 |
| SECTOR | 56% | **65%** | **73%** | 257 |
| MARKET | **70%** | 59% | 59% | 596 |

**Reading it**
- **Market and sector news carry real information.**
- **Company news points the wrong way:** after a "positive" item the stock lags NIFTY 57% of the time.
- **It is one 3-week window** in a falling market (NIFTY 22,753 against its 200-day average of 24,108). "Sell the news" and a base price that already contains the reaction (the snapshot is taken at scoring time, which `outcomes.py` itself notes) can both produce this.
- **Treat it as a red flag, not a finding.**

**Where news is used today**
- **Context (display only):**
  - Stock page news and analysis tabs; Market news and pulse.
  - Holdings "why it moved" line (`frontend/src/utils/money.js::whyLine`).
  - Needs-you bad-news actions and their AI notes (`summaries/holding.py`).
  - The pick detail page.
  - Chat facts (`ai/facts/market.py::news`).
  - The portfolio review's headlines and the rebalance AI list.
- **Decisions:**
  - `reactor.scan`: company news triggers LONGTERM buy proposals; 24 so far, all expired.
  - `autopilot` news entries, gated by `outcomes.proven` (theme weight > 1).
  - `fence`: risk-off from the regime tightens entries.
  - Portfolio verdict sentiment (`portfolio/rules.py`, capped by `AI_CAP`).
  - Game-plan revisions (`plan/revise.py`, tighten only).
  - Gap strategies' overnight catalysts (`datalayer/catalysts.py`).
  - Journal news findings (`journal/news.py`).
  - Conviction sizing: inert, since `AI_SIZING_WEIGHT = 0.0`.
- **Not used at all:**
  - Picks (`forecast/`), the factor book (`factor/`).
  - Rebalance targets (except as AI-list context), guardrails, options.
  - Tax harvesting, the weekly report, Home's Today digest attribution.

## Phase N0: make the signal trustworthy (blocks every "decision" use)

| # | Change | Where | Done when |
|---|---|---|---|
| N0.1 | **Stop company-news buy proposals and autopilot entries** until N0.3 shows company direction ≥ 52% (excess, 5d) on post-fix data. Sector/market uses stay. | `datalayer/reactor.py::scan`, `autopilot` news path (already behind `outcomes.proven`; make the company scope explicit) | Reactor test: a COMPANY-scope item makes no proposal; SECTOR/MARKET unchanged |
| N0.2 | **Measure from the right price.** Base = the last close *before* `published_at` (the `late` path exists) plus a "moved before we scored" field (return from publish to snapshot). Add a 20d horizon and an excess-vs-sector move. | `datalayer/outcomes.py::record/measure` | New fields on new outcomes; old rows untouched |
| N0.3 | **News accuracy report.** Hit rate and mean signed excess by scope × theme × impact bucket × source × scoring model, with a block-bootstrap t, 1d/5d/20d. Weekly job writes it; an admin page shows it. This is the bar every later phase reads. | new `datalayer/accuracy.py`, `routers/news.py`, Settings → AI or `/system` | Report served; numbers match a hand query |
| N0.4 | **Pipeline that cannot rot silently.** Retry `FAILED` with backoff (3 tries over 24h), then `DEAD`; alert when triage/score lag passes 30 min in session or NEW passes 500 (the 10-24 audit's silent-stop item). | `datalayer/news.py`, `system/status.py`, Telegram admin alert | Stalled-triage test fires the alert |
| N0.5 | **History to test on.** Backfill 2+ years of company, sector and market headlines from GDELT and NSE filings for the Nifty 200, scored by the same triage/score prompts (cheap tier, batched, its own daily budget separate from `NEWS_LLM_CALLS_PER_DAY`). Outcomes from stored daily bars. Without this, Phases N2 and N3 can only be forward-tested for months. | `datalayer/news_sources.py` (GDELT history), a one-off `python -m backend.datalayer.backfill_news` | ≥ 50k scored historical items; outcomes measured from bars |

**N2.1, N2.2, N2.5 status (2026-10-26):** one study tool (`backend/forecast/research/news_picks_tool.py`; rules in its docstring), runs on the N0.5 backfill once scored. Rule fixed before looking: news veto = direction <= -0.5 and impact >= 7 within 3 days up to the signal; results veto = NSE results filing inside the hold.

**N2.4 status (2026-10-26):** shipped. `no_buy_before_results_days` (Guardrails sheet, needs guardrails on): NeoTrade's own buys (chat, ticket, approve-live) are refused inside the window; broker-app buys raise a `results_buy` alert. Dates from the yfinance calendar, fetched on demand for unheld stocks.

**N0.5 status (2026-10-26):** tool built (`backend/datalayer/backfill_news.py`). GDELT is out: its DOC API throttles this VM (the live poll shares the IP). Sources are Google News month searches (day-level dates, 100 results per search cap: the market query hits it) and NSE filings (exact times). Owner approved building with a cost estimate before any LLM run. Caveat: the scorer post-dates the history, so the backfilled hit rate is an upper bound.

**Cost:** N0.5 is the expensive step, an LLM call per batch of about 150 headlines. Run it on the
fast tier with a hard budget, and check the cost estimate before running.

## Phase N1: news as context everywhere (ships now, changes no decision)

| # | Surface | What the user gets | Built from |
|---|---|---|---|
| N1.1 | **Ideas / Picks rows** | Fresh headline + direction chip; "results in N days" flag; "bad news since signal" flag on older picks | `/news/symbols`, `catalysts`/results calendar |
| N1.2 | **Stock chart** | News markers on the price chart (impact-sized dots, tap for headline), beside the existing trade markers | `news_items` by symbol |
| N1.3 | **Money → Holdings** | Per-row sentiment dot and "news today" badge; filter chip "Has news" | `/news/symbols` (`whyLine` already reads the headline) |
| N1.4 | **Rebalance + AI final list** | Each trade row shows its latest material headline and next results date; the AI prompt gets sentiment and the catalyst date per holding | `ai_rebalance.py` lines, `RebalanceAfter` |
| N1.5 | **Home / Today digest** | "What news moved your money": each big holding move matched to the news item that preceded it, or "moved with the market" | `portfolio/digest.py` + `news_outcomes` |
| N1.6 | **Weekly report** | News attribution for the week; themes that hit your book; the news accuracy line from N0.3 | `WeeklyReport`, `summaries/weekly.py` |
| N1.7 | **Journal** | Every round trip tagged with the news around entry and exit; the habit finding "you buy after good news: net X across N trades" (extends `journal/news.py` to exits) | `journal/news.py`, `insights.py` |
| N1.8 | **Market tab** | Sector heat with sector sentiment beside sector move; flags divergence (good news, falling price) | `sector_sentiment:*`, `/market/scan` |
| N1.9 | **Tax tab** | Loss-harvest candidates show whether fresh news is behind the loss (harvesting a news-driven drop vs a slow bleed) | `mine/tax.py` harvest list + `/news/symbols` |

None of these needs new LLM calls. They all read what the engine already stores.

## Phase N2: news as a measured filter (needs N0.3 + N0.5 evidence)

Each item ships only if the backfilled study shows the filter **improves** the thing it filters,
using the same yardstick that thing already uses.

| # | Filter | Yardstick to pass |
|---|---|---|
| N2.1 | **Picks news veto:** drop or flag a pick with a high-impact negative item in the 3 days before signal, or results inside its horizon | Picks study: adjusted OOS excess up and t not down (`forecast/study.py::adjusted_edge`), on the vetoed vs kept split |
| N2.2 | **Sector tailwind tilt:** rank picks within a grade by sector 5d sentiment (sector scope is the measured-good one) | Same study, rank IC of the tilt > 0 in ≥ 70% of test years |
| N2.3 | **Verdict sentiment weight from evidence:** `portfolio/rules.py` sentiment counts only for themes whose N0.3 hit rate clears the bar; others count 0 | Verdict back-test on snapshots; or a forward 60-day comparison |
| N2.4 | **Guardrail "no new buy into results":** user-set guardrail blocking a buy within N days before a results date | Risk control, not an edge claim: ships after N1 as a user option |
| N2.5 | **Regime tilt for baskets:** market/sector scope sets basket size (fewer names in risk-off), tighten only like the fence | Picks basket study by regime bucket (`basket` from 2026-10-26) |

**Result 2026-10-28 (closed, nothing ships).** `news_picks_tool` on 60,834 backfilled items
(2024-10..2026-10), 8 setups x 4 filters, output in `/home/ubuntu/runs/neotrade-n05/news_picks.txt`.
No filter reached t >= 2.5; with 32 tests a Bonferroni bar removes every nominal pass.
N2.1 veto passed only on pullback (kept +0.37% vs all +0.30%, t 0.5). N2.2 passed only on
momentum_vol_60 (3 test years). N2.5 regime passed on momentum, breakout, low_vol, but on 3-11
months per bucket. N2.4 (guardrail) shipped earlier as a risk control. Owner chose to close N2
and skip N3; revisit only after another year of live news.

## Phase N3: news as a signal source (only what proves itself)

| # | Candidate setup | Bar (same as the strict bar in `forecast/research/new_setups_tool.py`) |
|---|---|---|
| N3.1 | **Sector news momentum:** sector 5d sentiment in the top tercile, buy that sector's relative-strength leaders | Adjusted OOS excess > 0, t ≥ 2.5, positive in ≥ 70% of test years, survives Bonferroni over every news variant tried |
| N3.2 | **Company-news fade (contrarian):** only if N0.2's corrected measurement still shows company direction < 48% | Same bar; plus it must hold in both up and down market halves |
| N3.3 | **Unlock news in conviction:** raise `AI_SIZING_WEIGHT` above 0 | Owner decision 2026-10-24 kept it at 0. Proposed criterion: N0.3 shows ≥ 55% 5d excess hit, t ≥ 2, n ≥ 500 per scope used, in 2 regimes. `AI_CAP = 0.30` stays. |

Anything that passes enters as an ordinary `Setup` / `Intent` through `composite.py`. There is
no second blend.

## Order and size

1. **N0.1** (a day): stops a known-bad signal from making ideas.
2. **N0.4** (a day): the silent-stall risk, already flagged in the 10-24 audit.
3. **N1.1–N1.4** (2–3 days): visible value, no risk.
4. **N0.2 + N0.3** (2–3 days): the accuracy report every later step reads.
5. **N1.5–N1.9** (3–4 days).
6. **N0.5 backfill** (2 days of build, then runtime and LLM budget): owner sign-off on cost first.
7. **N2**, then **N3**: each item a study first, shipped only if it passes.

## Owner questions

1. N0.1: pause company-news buy proposals now? Recommended: yes, given the 42% hit.
2. N0.5: approve a one-off LLM budget for scoring about 2 years of headlines (estimate before running)?
3. N3.3: is the stated bar for letting news into sizing acceptable?
