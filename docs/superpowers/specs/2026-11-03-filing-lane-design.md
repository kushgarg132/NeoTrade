# Filing lane: read NSE filings fast and record what they do

Status: design, awaiting owner review. Date: 2026-11-03.

## Goal

The owner wants news the AI account can trade on, intraday, starting from NSE filings. This
phase answers one question before any trading is built: **do filings, properly read and scored
fast, predict the next hour well enough to pay for intraday charges?**

This phase places no orders. It records.

## Why this shape

Measured on production, 5 Oct to 3 Nov 2026:

| Finding | Evidence |
|---|---|
| Company news has no live edge at 5 days | 1,325 rows, hit 45%, mean -0.06%, t -0.2 |
| Most sources are too slow for intraday | In session, published to scored: all sources median 60 min, 90% within about 39 h; NSE filings median 7 min, 90% within 14 min |
| The scorer cannot read filings | 677 of 956 are boilerplate only; median text 113 characters |
| So strong filing scores are rare | 6 at impact 7 or more in a month; 9 measured rows in session |
| The PDFs are readable | 20 of 20 sampled parsed with `pypdfium2` (already installed), none scanned, about 0.1 s each, median 5,205 characters |
| Only part of the volume is in session | 254 of 956 filings between 9:15 AM and 3:00 PM |
| The feed is a short window | `corporate-announcements` returned 20 rows, polled every 60 s |

A one-hour pattern exists on news feeds (bullish after 3% or more: n 103, hit 62%, +0.27%;
bearish after 3% or more: n 32, hit 66%, +0.31%, before charges). It was found by looking at
the data and is almost entirely not filings, so it motivates this test and proves nothing.

## Decisions taken with the owner

1. Scope: pipeline reliability, then an edge test, then a paper book only if the test passes.
   Live money is a separate later decision.
2. Style: intraday.
3. Source: NSE filings only.
4. First step: read the PDFs and record for 4 to 6 weeks, with no trades.

This reverses in part the 2026-11-02 decision that rotation is the autopilot's only entry
source, but only if the bar below is passed and the owner then approves a paper book. Until
then that decision stands unchanged.

## Non-goals

- No order path, no paper book, no 5-minute bars, no shorts (the fence refuses them; see "After the review").
- No change to `sentiment:`, the rotation veto, alerts, conviction or `AI_SIZING_WEIGHT`.
- No work on the slower news-feed pipeline's lag.
- The existing filing path through `news_items` stays as it is, so nothing that reads it changes.

## Design

### 1. Fast lane (`backend/datalayer/filings.py`, new)

A new ingest loop, leader only, about every 20 seconds:

1. Fetch `corporate-announcements` through the existing `news_sources` session and headers.
   Back off on errors. If NSE starts refusing at this rate, fall back to the rate it accepts
   and record that.
2. Keep filings of followed symbols (`news.followed`: Nifty 200 plus held and watched), minus
   the routine types `parse_nse` already skips.
3. Claim each new filing once. The id is a hash of symbol, description and exchange time, so a
   restart or a second worker does not score it twice.
4. Download the PDF and extract text with `pypdfium2`.
5. Score it (section 2), then snapshot prices (section 3).

Download limits, because this is untrusted content from the internet:

- HTTPS and host `nsearchives.nseindia.com` only; anything else is not fetched.
- 10 MB cap, read as a stream, 20 s timeout.
- First 6 pages, first 8,000 characters. Parsed in memory, never written to disk.
- A failed download or parse scores on the API text with `pdf_ok: false`. Those rows are
  excluded from the pass bar.

### 2. Scoring (`backend/prompts/score_filing.md`, new)

One call per filing, `standard` tier to start, feature `news`, so latency is one call and not a
batch. About 30 calls a day at current volume, with a hard cap of 120 a day. An outage retries
on the next pass; after 3 failures the filing is marked failed and counted.

Output, validated by a pydantic model and clamped:

| Field | Meaning |
|---|---|
| `event_type` | results, order, deal, legal, regulatory, management, capital, other |
| `direction` | -1 to 1, what the filing means for the company's value, whatever the price did |
| `impact` | 1 to 10 |
| `priced_in` | 0 to 1, how much the price already holds |
| `key_fact` | a short quote from the filing, which must appear in the text |

A `key_fact` not found in the extracted text clears the score to no signal and is counted: it
catches a model describing a document it did not read. Figures go through `check_fields`.

The prompt treats filing text as data, never as instructions. The model sees the stock's move
since the last close and over 5 sessions (`news.price_notes`), the same point-in-time rule as
`score_market_news` v2. It gets no user data.

### 3. Measurement (`filing_scores`, new collection, Atlas)

One document per filing: identity, exchange time, `seen_at`, `pdf_ok`, the text kept for audit,
the score, `model`, `prompt` (`prompt_id`), and timings.

After each close, a pass reads Yahoo 1-minute bars for the day's filings. The cached quotes cannot
do this job: they are 5-minute bars, and most Nifty 200 names refresh only every 5 minutes. Bars read
after the fact also mean a restart cannot lose a horizon. Yahoo keeps them about 7 days, so a filing
with no bars by then ends unmeasured, with no figure.

The entry is the open of the first full minute after scoring, so nothing is known that a trader
could not have known. It stores the price at +15 minutes, +1 hour and the 3:15 PM square-off, and
the move before entry net of Nifty, from the last daily close.

Each row stores a hypothetical trade: the signed return after `MIS` charges and slippage through
`lab/assumptions.py::round_trip_return(product="MIS")`, so the charge rules exist in one place.
Filings after 2:15 PM cannot complete an hour and do not count toward the bar. After-hours
filings are measured from the next open and are exploratory.

Only the first signal per symbol per day counts toward the bar, because a revised filing is not
a second piece of evidence.

### 4. Reliability

- Recorded per filing: exchange time to seen, seen to PDF read, read to scored.
- Counted daily: filings seen, PDF failures, scoring failures, `key_fact` rejections.
- Coverage: if a poll shares no row with the previous poll, the 20-row window may have dropped
  filings; count it. Check in the plan's first task whether the API accepts a date range. If it
  does, a daily reconcile counts real misses and scores them as late, which do not count toward
  the bar.
- A `filings` heartbeat on `/health`, and a Telegram alert when the lane stalls in session, using
  the existing stall alert pattern.

### 5. Report and Lab view

- `accuracy.py`: a cell also carries `days` (distinct trading days) and is `thin` under 20 days
  as well as under 30 rows, which fixes the t = 31.4 reading on 290 rows. The N0.1 gate keeps its
  own rule.
- `filings.report`: the primary rule's standing against the bar, then exploratory splits by event
  type, impact, `priced_in` and confirmation size, each labelled exploratory.
- A card on the admin News accuracy page, plus lag and failure counts. It offers no action.

## The pass bar, fixed before any data

**The one rule under test:**

- `|direction| >= 0.5`, `pdf_ok`, scored between 9:15 AM and 2:15 PM IST on a trading day.
- The stock has already moved 1% or more in the filing's direction since the last close, net of
  Nifty's move. The entry is the first minute's open after scoring.
- Long if bullish, short if bearish. Hold 1 hour.

**It passes only if, all together:**

1. At least 100 signals, over at least 20 trading days.
2. Mean return per trade above zero, after charges and slippage.
3. t >= 2, resampling whole days as `accuracy._stats` does.

Long-only results are reported beside these. The fence refuses shorts, so if the owner keeps that
rule, the long side must pass the same bar alone.

Every other split is exploratory and cannot pass. A promising one becomes a new rule and starts
counting from zero on new data.

**Review at 6 weeks (about 15 Dec 2026):**

| Result | Decision |
|---|---|
| Passes | Design the paper book and take the shorts decision |
| Under 100 signals, nothing conclusive | Keep recording, review again at the next 100 |
| 100 or more signals and fails | Filings stay context only; no trading path gets built |

## After the review (not this phase)

A paper book needs its own spec: fence changes for shorts, intraday marks, and how a news entry
fits the invariants. A trade would still need a rule-based setup, since AI cannot rescue a trade
the rules did not support, and would still pass the fence and kill switch, with `reason_codes`
and code-based sizing. Passing here does not approve it.

## Invariants kept

- Nothing in this phase can place an order or reach `autopilot/service.py`.
- `filing_scores` is read by nothing except its report and Lab card.
- Market-wide reference data with no user data, so no `user_id` is needed and nothing is
  published as advice. The Lab card is admin only.
- Every prompt lives in `backend/prompts/`.

## Risks

| Risk | Handling |
|---|---|
| NSE blocks 20-second polling | Back off, record the rate that works; slower polling weakens the intraday case, and the numbers will show it |
| 100 signals take many months | Expected possibility; the review says keep recording, and nothing trades meanwhile |
| Yahoo's 1-minute bars have gaps | A missing price leaves that horizon unmeasured, never a zero |
| The model hallucinates a filing | `key_fact` must appear in the text, and the rejection count is visible |
| A malicious PDF or prompt injection | Host allowlist, size cap, in-memory parsing in the existing library, text as data, and nothing downstream can act |
| Atlas's 512 MB cap | About 30 filings a day at up to 8 KB is around 7 MB a month; watch it at the review |
| Disk on this VM (89% used) | No PDFs stored, no new image dependency |

## Testing

- Unit: filtering and the id, host allowlist and size cap, text extraction on a fixture PDF,
  `key_fact` check, the hypothetical trade and its charges, first-signal-per-day, the rule and
  bar, `thin` with `days`.
- Check: `backend/tests/test_llm_call_tiers.py` lists the new call; `test_prompts.py` covers the prompt.
- A guard test: no module in the lane imports `autopilot` or an order path.
- Before release: a read-only replay over recent filings in the production image to see the
  scores, the rejection rate and real cost.

## Done when

- The lane runs in production through a full session with its heartbeat, and lag, failure and
  coverage numbers are visible in Lab.
- Median exchange time to scored is under about 2 minutes in session. If it is not, record why.
- Wiki and handbook pages are updated in the same commits.
