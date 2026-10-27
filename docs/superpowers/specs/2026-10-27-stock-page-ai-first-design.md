# Stock page: AI read first

Date: 2026-10-27. Status: approved in chat, awaiting spec review.

## Problem

The AI analysis on `/stock/:symbol` runs only when the Analysis tab opens (`AnalysisTab.jsx` calls
`useStockAnalysis.requestAi`). Most visits never see it. When it does run cold it costs two LLM calls in a row
(`ai/analyst.py`: `_score_news` on the `deep` tier, then `_report` on `standard`), roughly 30-60 s, with a
skeleton and no output until the end. The cached read (`analyst:{symbol}`, 4 h) disappears after 4 h, so a
stock opened the next morning has nothing to show.

## Goal

Every time a stock is opened, an AI read is on screen at once, and it refreshes itself when stale. A stock with
no read yet shows progress and streams its note word by word instead of a blank wait.

Owner choices (2026-10-27): show the last read instantly and refresh in the background when stale (not a fresh
model run on every open, not a pre-compute job); AI card at the top with tabs below; instant read and
word-by-word streaming both in this pass. Faster-tier news scoring was rejected: it lowers the quality of the
sentiment the engine reads.

## Non-goals

- No change to the analysis content, prompts, tiers or the sentiment formula.
- No pre-computation job; nothing runs for stocks nobody opens.
- No change to `POST /agents/analyze` (HTTP) or to the other callers of `AnalystAgent` (suggestion theses,
  analyst-verdict refresh).

## Backend

### Last read and staleness (`backend/ai/analyst.py`)

- Every write of a read (`_store`, `_store_note`) also writes `analyst:last:{symbol}` = the read plus
  `at` (ISO UTC), TTL `LAST_TTL_SECONDS` = 7 days. `analyst:{symbol}` (4 h) and its readers are unchanged.
- `async def latest(symbol) -> dict | None`: `{read, at, stale}` from `analyst:last:{symbol}`; `None` when there
  is no last read. `stale` is true when:
  - in session (`core/market_calendar.py::market_phase(now)` is the open phase), `at` is older than
    `FRESH_IN_SESSION` = 1 h;
  - outside a session, `analyst:{symbol}` has expired (older than 4 h).
  For followed symbols, a run started because the read is stale still goes through `datalayer/analysis.py::
  from_layer`, which returns the cached read unchanged when its news basis has not moved.
- One run per symbol: the `analyst:lock:{symbol}` set-NX-and-wait pattern from `from_layer` is applied to the
  non-followed path in `AnalystAgent.analyze` as well (today only followed symbols take it, so two users
  opening the same cold stock both pay).

### Streaming (`backend/llm.py`, `backend/ai/analyst.py`)

- `llm_service.stream_completion(prompt, system_prompt, tier=None, feature=None)`: async generator of text
  deltas over `astream_events` (`on_chat_model_stream` chunks, the chat path). Same `feature_enabled`,
  `_charge` (daily cap) and `_note` (llm:last_ok / last_error) as `get_completion`. A failure before the first
  chunk falls back to `get_completion` and yields its whole answer as one chunk; a failure after it raises.
  `LLM_DISABLED` behaves as in `get_completion`.
- `report_sink: ContextVar[Callable | None]` in `ai/analyst.py`. When set:
  - `_analyze` calls `sink({"type": "stage", "step": "news", "count": n})` after the news fetch and
    `sink({"type": "stage", "step": "writing"})` before the note; `datalayer/analysis.py::_build` sends the
    `writing` stage the same way;
  - `_report` uses `stream_completion` and calls `sink({"type": "delta", "text": d})` per delta, then joins the
    deltas and splits on `THESIS_MARKER` exactly as today.
  Unset (every caller except the socket), `_report` makes today's single `get_completion` call.

### Socket `analyze` action (`backend/ws/routes.py::_stream_analysis`)

Frames on `analysis:{req_id}`, in order:

1. `cached` `{read, at, stale}` from `latest(symbol)`, or `{read: null, stale: true}`. Sent before any budget
   check: a cached open is free.
2. If not stale: `done` and stop.
3. If stale: the existing per-user budget (`_BUDGETS["analyze"]`, 10/min) and daily LLM cap now apply here.
   Over budget: `error` with the existing text, and the client keeps the cached read.
4. `stage` frames, `delta` frames, then `report` (the final `ResearchReport`, the same shape as today), set up by
   setting `report_sink` around `research_agent.run(symbol)`.
5. Any failure: `error` `{detail}`.

A second socket that opens the same symbol while another run holds the lock receives no `stage`/`delta`; it waits
on the lock and gets `report`.

### HTTP fallback

`GET /research/{symbol}/note` (`routers/market_data.py::get_cached_note`) reads `latest(symbol)` and adds
`read`, `at`, `stale` to its existing `{summary, thesis, as_of}` (`as_of` = `at`); 404 when there is no last
read or its summary failed, as today. Additive: `pages/IdeaDetail.jsx` still reads `summary` and `as_of`.

## Frontend

### Page order (`pages/Stock.jsx`)

Header (symbol, verdict badge) -> price block (the one-line "AI summary" strip and its `stockNote` read are
removed) -> your position (when held) -> AI card -> tabs **Chart / News / Details / Events**.

### AI card (`components/stock/AiRead.jsx`)

| State | Shows |
|---|---|
| Fresh read | Sentiment label and score (`SentimentPanel`'s read-out), summary via `AiMarkdown` collapsed to ~3 lines; "Read more" expands it and shows the thesis. Footer "Based on N articles · as of 14:20". |
| Stale read | Same, plus an "Updating…" chip. Once deltas arrive the summary is replaced live; on `report` the card shows the new read and as-of. |
| No read yet | Stage line ("Reading 12 headlines…", then "Writing the note…"); skeleton until the first delta, then the summary streams. |
| Refresh failed | Last read kept, muted "Couldn't refresh: <reason>" with Retry. No read: error line with Retry. |
| AI off / daily limit | Last read if any, plus a one-line reason; no spinner. |

Streamed text after `===THESIS===` is held back (shown only under "Read more"); the marker is never rendered.

### Tabs

- **Details** (`components/stock/DetailsTab.jsx`, from `AnalysisTab.jsx`): Our verdict and Your thesis (when
  held), then `TechGauge`, `StockFlags`, `TradingLevels`, `Fundamentals`. No AI panel.
- **News**, **Events**: unchanged inputs (`ai` state); Events picks up the new events when `report` lands.
- `?tab=analysis` maps to `details` (old links). "Set one in Analysis" becomes "Set one in Details". NewsTab's
  "Open analysis" scrolls to the AI card.

### Hook (`components/stock/useStockAnalysis.js`)

- Sends `analyze` on mount alongside `quick_analyze`; changing symbol cancels the old request.
- AI state from a pure reducer `aiReducer(state, frame)` in `utils/aiRead.js`:
  `{symbol, read, at, stale, stage, text, streaming, error}`; frames `cached`, `stage`, `delta`, `report`,
  `error`, `done`. An `error` keeps `read`. A frame for another symbol is ignored.
- `splitThesis(text) -> {summary, thesis}` in the same file.
- HTTP fallback (no socket): `GET /research/{symbol}/note`, then `POST /agents/analyze` when stale (no
  streaming).
- `requestAi` stays as Retry. `ai.data` keeps today's `ResearchReport` shape for `NewsTab` and `EventsTab`.

## Cost

A stock's model run happens at most once per hour in session (once per 4 h outside), shared by every user, and
only for stocks someone opens. Repeat and concurrent opens cost nothing. Today's cost per run is unchanged.

## Testing

Backend (pytest):
- `latest`: in session older than 1 h is stale, under 1 h is fresh; outside a session stale exactly when
  `analyst:{symbol}` is gone; no last read is `None`; writes set `analyst:last:{symbol}` with `at`.
- `stream_completion`: yields chunks; falls back to `get_completion` on a failure before the first chunk;
  raises after it; charges the daily cap once.
- `_report` with a sink: joined deltas equal the stored summary + marker + thesis; without a sink, one
  `get_completion` call as today.
- Socket: frames `cached`, `stage`, `delta`..., `report` when stale; `cached`, `done` when fresh; a fresh open
  does not touch the per-user budget; over budget gives `error` after `cached`.
- Lock: two concurrent cold runs for a non-followed symbol call the model once.

Frontend (node test):
- `aiReducer`: frame order; stale -> streaming -> fresh; error keeps the read; another symbol's frame is
  ignored.
- `splitThesis`: marker split, marker not in the summary, partial marker at a chunk edge not shown.
- `?tab=analysis` -> `details`.

Then `npm run lint`, `npm test`, `npm run build`, full pytest.

## Docs

`docs/wiki/frontend.md` (Stock flow), `docs/wiki/data-ai-jobs.md` (analyst cache, streaming, socket frames),
`frontend/src/handbook/ai-and-news.md`, each with `verified_at`.
