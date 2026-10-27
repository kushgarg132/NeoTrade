# Stock page AI-first Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every stock open shows the last AI read at once, refreshes it in the background when stale, and streams
a cold read word by word.

**Architecture:** `ai/analyst.py` keeps a 7-day last-read copy and decides staleness; `llm.stream_completion` streams
the note; a ContextVar sink carries stages and deltas from `_report` to the socket's `analyze` action, which sends
`cached` first and runs only when stale. The frontend folds the frames through a pure reducer into a new AI card
above the tabs.

**Tech Stack:** FastAPI, redis.asyncio, LangChain `astream_events`, pytest (asyncio_mode=auto); React 19, node:test.

**Spec:** `docs/superpowers/specs/2026-10-27-stock-page-ai-first-design.md`

## Global Constraints

- `LAST_TTL_SECONDS = 7 * 24 * 3600`; `FRESH_IN_SESSION = 3600`; `CACHE_TTL_SECONDS` stays `4 * 60 * 60`.
- Redis keys: `analyst:{symbol}` (unchanged), `analyst:last:{symbol}` (new), `analyst:lock:{symbol}` (existing).
- In session = `core/market_calendar.py::market_phase(now) == "session"`.
- `THESIS_MARKER = "===THESIS==="` is never rendered in the UI.
- Socket topic stays `analysis:{req_id}`; events `cached`, `stage`, `delta`, `report`, `error`, `done`. The old
  `started` frame is replaced by `cached`.
- `cached` is sent before any budget check; `_BUDGETS["analyze"]` (10/min) and the daily LLM cap apply only to a run.
- No prompt, tier or sentiment-formula change. Callers other than the socket see no behaviour change.
- `GET /research/{symbol}/note` stays additive: `summary`, `thesis`, `as_of` kept (`pages/IdeaDetail.jsx` reads them).
- Every LLM prompt stays in `backend/prompts/*.md`. Frontend charts/colours: DESIGN.md tokens only.
- Backend tests run in `neotrade-verify:main` (host Python lacks deps):
  `docker run --rm -v "$PWD":/src -w /src --entrypoint sh neotrade-verify:main -c "python -m pytest -q -p no:cacheprovider <path>"`.
- Frontend: `cd frontend && npm test`, `npm run lint`, `npm run build`.

## Review Focus

1. Socket drops mid-stream, or the user opens another stock: the old request's deltas must not land in the new
   stock's card (reducer ignores other symbols; hook cancels) — Task 5 and Task 6 tests.
2. Stream fails after some deltas: the card must not keep half a note as if final; it keeps the last full read and
   shows the error — Task 5 reducer test `error after deltas restores the last read`.
3. `===THESIS===` split across two deltas (`===THE` + `SIS===`): no fragment of the marker shows — Task 5
   `splitThesis` partial-marker test.
4. Daily cap reached on a stale open: the user still sees the cached read with a reason, and no run starts —
   Task 4 test `over budget after cached`.
5. Redis down: `latest()` returns `None` and the page falls back to a plain run, not a crash — Task 1 test
   `latest without redis is None`.

---

### Task 1: Last read, staleness, shared lock (`backend/ai/analyst.py`)

**Files:**
- Modify: `backend/ai/analyst.py` (`_store`, `_store_note`, `AnalystAgent.analyze`, new `latest`)
- Test: `backend/tests/test_analyst_latest.py` (reuse the `_Redis` fake pattern from `test_analyst_agent.py`;
  add `delete`, and `set(..., nx=True)` returning False when the key exists)

**Interfaces:**
- Produces: `LAST_TTL_SECONDS: int`, `FRESH_IN_SESSION: int`,
  `async def latest(symbol: str, now: datetime | None = None) -> dict | None` returning
  `{"read": dict, "at": str, "stale": bool}`. Every stored read carries `"at"` (ISO UTC).

- [ ] **Step 1: Write the failing tests**

```python
async def test_store_writes_the_last_read_with_at(wired):       # after AnalystAgent().analyze(...)
    raw = json.loads(redis.store["analyst:last:SBIN"]); assert raw["at"]
    assert redis.ttls["analyst:last:SBIN"] == analyst.LAST_TTL_SECONDS

async def test_in_session_under_an_hour_is_fresh(...):   # market_phase -> "session", at = now - 30 min
    assert (await analyst.latest("SBIN", now))["stale"] is False
async def test_in_session_over_an_hour_is_stale(...):    # at = now - 61 min
async def test_outside_session_stale_only_when_the_4h_key_is_gone(...):  # phase "post": with analyst:SBIN -> False; without -> True
async def test_no_last_read_is_none(...)
async def test_latest_without_redis_is_none(monkeypatch):  # _redis -> None
async def test_two_cold_runs_for_an_unfollowed_symbol_call_the_model_once(...):
    # from_layer returns None; asyncio.gather two analyze() calls; llm.await_count == 2 (score + report, once)
```

- [ ] **Step 2: Run to verify they fail** — command from Global Constraints with `backend/tests/test_analyst_latest.py`; expected: AttributeError `latest`.

- [ ] **Step 3: Implement**
  - `_store` and `_store_note` set `output["at"] = datetime.now(timezone.utc).isoformat()` and also write
    `analyst:last:{symbol}` with `ex=LAST_TTL_SECONDS`.
  - `latest` reads `analyst:last:{symbol}`; stale per Global Constraints (outside session: `await redis.exists`
    or `get` of `analyst:{symbol}` is None). Any Redis exception -> `None`.
  - In `AnalystAgent.analyze`, after the cache miss and before `_analyze`, take `analyst:lock:{symbol}`
    (`set nx=True ex=LOCK_SECONDS`, import `LOCK_SECONDS`, `WAIT_SECONDS` from `datalayer/analysis.py`); a loser
    polls `_cached` every 2 s up to `WAIT_SECONDS` and returns it when present; the winner deletes the lock in
    `finally`.

- [ ] **Step 4: Run Task 1 tests and `backend/tests/test_analyst_agent.py`** — expected: all pass.
- [ ] **Step 5: Commit** `feat(analyst): keep the last read a week, say when it is stale, one run per stock`

### Task 2: `llm.stream_completion` (`backend/llm.py`)

**Files:**
- Modify: `backend/llm.py` (add method on the service class next to `get_completion`)
- Test: `backend/tests/test_llm_stream.py` (follow `test_llm.py::test_stream_falls_back_only_before_any_event` fakes)

**Interfaces:**
- Produces: `async def stream_completion(self, prompt: str, system_prompt: str, tier: str | None = None, feature: str | None = None) -> AsyncIterator[str]`
  on `llm_service`. Yields text deltas; yields `"LLM_DISABLED"` once when `get_llm` returns None.

- [ ] **Step 1: Write the failing tests**

```python
async def test_stream_yields_each_chunk(...):           # fake astream_events emits on_chat_model_stream "Hel","lo"
    assert [d async for d in llm_service.stream_completion("p", "s")] == ["Hel", "lo"]
async def test_failure_before_first_chunk_falls_back_to_get_completion(...):  # yields ["whole answer"]
async def test_failure_after_a_chunk_raises(...)
async def test_disabled_feature_yields_llm_disabled(...)
async def test_content_block_chunks_are_joined_text(...)  # chunk.content = [{"text": "a"}] -> "a"
```

- [ ] **Step 2: Run, expect AttributeError.**
- [ ] **Step 3: Implement** — `get_llm(tier, feature)` (charges once), messages as in `get_completion`, iterate
  `llm.astream_events(messages, version="v1")`, yield `event["data"]["chunk"].content` text for
  `on_chat_model_stream`; record `_note(LLM_OK_KEY…)` at the end and `_note(LLM_ERROR_KEY…)` on error, as
  `get_completion` does. Fallback before first chunk: `yield await self.get_completion(...)` without a second charge
  (call the underlying `llm.ainvoke` path, not `get_llm` again).
- [ ] **Step 4: Run Task 2 tests and `test_llm.py`** — pass.
- [ ] **Step 5: Commit** `feat(llm): stream_completion yields the model's text as it is written`

### Task 3: Report sink — stages and deltas (`backend/ai/analyst.py`, `backend/datalayer/analysis.py`)

**Files:**
- Modify: `backend/ai/analyst.py` (`report_sink`, `_analyze`, `_report`), `backend/datalayer/analysis.py::_build`
- Test: `backend/tests/test_analyst_stream.py`

**Interfaces:**
- Consumes: Task 2 `llm_service.stream_completion`.
- Produces: `report_sink: ContextVar[Callable[[dict], None] | None]` (default None) in `backend/ai/analyst.py`.
  Sink payloads: `{"type": "stage", "step": "news", "count": int}`, `{"type": "stage", "step": "writing"}`,
  `{"type": "delta", "text": str}`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_with_a_sink_the_note_streams_and_joins_to_the_stored_text(wired_stream):
    events = []; token = analyst.report_sink.set(events.append)
    out = await AnalystAgent().analyze({"symbol": "SBIN"}); analyst.report_sink.reset(token)
    assert events[0] == {"type": "stage", "step": "news", "count": 3}
    assert {"type": "stage", "step": "writing"} in events
    joined = "".join(e["text"] for e in events if e["type"] == "delta")
    assert joined == REPORT
    assert (out["summary"], out["thesis"]) == analyst._split_report(joined)
async def test_without_a_sink_one_get_completion_call_as_today(wired)  # stream_completion not called
async def test_layer_build_sends_the_writing_stage(...)                # datalayer/analysis._build with sink set
```

- [ ] **Step 2: Run, expect failure (no `report_sink`).**
- [ ] **Step 3: Implement** — `_analyze` calls the sink with the news stage after the fetch (count = articles kept)
  and the writing stage before `_report`; `_build` sends the writing stage before its `_report`. `_report`: sink
  set -> collect deltas from `stream_completion(..., tier="standard", feature="research")`, call the sink per delta,
  join, then `_split_report`; unset -> today's `get_completion`. Exceptions keep today's `"Unable to generate
  summary."` path.
- [ ] **Step 4: Run Task 3 tests, `test_analyst_agent.py`, `test_analyst_latest.py`** — pass.
- [ ] **Step 5: Commit** `feat(analyst): a sink streams the note and its stages to whoever set it`

### Task 4: Socket `analyze` frames and note endpoint (`backend/ws/routes.py`, `backend/routers/market_data.py`)

**Files:**
- Modify: `backend/ws/routes.py` (budget for `analyze` moves out of the generic `_BUDGETS` pre-check into
  `_stream_analysis`; `_stream_analysis`), `backend/routers/market_data.py::get_cached_note`
- Test: `backend/tests/test_ws_routes.py` (update `test_analysis_streams_back_on_its_own_topic`: `started` ->
  `cached`), new cases there; `backend/tests/test_research_note.py`

**Interfaces:**
- Consumes: Task 1 `latest`, Task 3 `report_sink`.
- Produces (frames on `analysis:{req_id}`): `cached {read: dict|null, at: str|null, stale: bool}`;
  `stage {step, count?}`; `delta {text}`; `report <ResearchReport>`; `error {detail}`; `done {}`.
  Note endpoint: `{summary, thesis, as_of, read, at, stale}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_fresh_read_sends_cached_then_done_and_no_run(client, monkeypatch):
    # latest -> {"read": {...}, "at": "...", "stale": False}; ResearchAgent.run must not be called
    assert [f["event"] for f in frames] == ["cached", "done"]
def test_a_stale_read_streams_stage_delta_then_report(client, monkeypatch):
    # fake agent.run calls analyst.report_sink.get()({"type":"stage","step":"writing"}) then a delta
    assert [f["event"] for f in frames] == ["cached", "stage", "delta", "report"]
def test_a_fresh_open_does_not_touch_the_budget(client, monkeypatch)   # allow() not called
def test_over_budget_after_cached_sends_error_and_keeps_no_run(client, monkeypatch)  # ["cached", "error"]
def test_note_returns_read_at_stale_and_the_old_fields(...)            # GET /research/SBIN/note
def test_note_is_404_without_a_last_read(...)
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement** — `_stream_analysis`: `cached` from `latest(symbol)` (None -> `{read: None, at: None,
  stale: True}`); not stale -> `done`; stale -> `allow(db.redis, f"analyze:{user}", 10, 60)` else `error`; set
  `report_sink` to a function that offers `stage`/`delta` frames, run, reset the token in `finally`, then `report`.
  Errors as today. `get_cached_note`: from `latest`; 404 when None or summary is empty/`"Unable to generate
  summary."`; `as_of = at`.
- [ ] **Step 4: Run Task 4 tests and full `test_ws_routes.py`** — pass.
- [ ] **Step 5: Commit** `feat(ws): analyze sends the cached read first and streams a run only when stale`

### Task 5: Pure AI-read state (`frontend/src/utils/aiRead.js`, `frontend/src/utils/stocks.js`)

**Files:**
- Create: `frontend/src/utils/aiRead.js`, `frontend/src/utils/aiRead.test.js`
- Modify: `frontend/src/utils/stocks.js` (add `stockTab`), its test file (or `aiRead.test.js`)

**Interfaces:**
- Produces:
  - `AI_EMPTY = { symbol: null, read: null, at: null, stale: false, stage: null, text: '', streaming: false, error: null, loading: true }`
  - `aiReducer(state, { symbol, event, data }) -> state` — `reset` event (`{symbol}`) starts a symbol; frames for
    another symbol return `state` unchanged; `cached` sets read/at/stale, `loading: false` when not stale or a read
    exists; `stage` sets stage, `streaming: true`; `delta` appends to `text`; `report` sets `read = data`,
    `at = now ISO`, `stale: false`, clears stage/text/streaming/error; `error` sets error, clears text/stage/
    streaming, keeps read; `done` clears loading/streaming.
  - `splitThesis(text) -> { summary, thesis }` — split on `===THESIS===`; a trailing partial prefix of the marker
    (`=`, `===TH`, …) is dropped from `summary`.
  - `stockTab(id) -> 'chart'|'news'|'details'|'events'` — `'analysis'` -> `'details'`, unknown -> `'chart'`.

- [ ] **Step 1: Write the failing tests** (node:test, `assert/strict`)

```js
test('cached fresh read stops loading', ...)            // stale:false -> loading false, read set
test('stale cached read then deltas then report swaps the read', ...)
test('error after deltas restores the last read and drops the partial text', ...)
test('a frame for another symbol is ignored', ...)
test('splitThesis splits on the marker and hides it', ...)  // 'A===THESIS===B' -> {summary:'A', thesis:'B'}
test('splitThesis hides a marker cut at a chunk edge', ...) // 'A\n===THE' -> summary 'A'
test('stockTab maps analysis to details', ...)
```

- [ ] **Step 2: `cd frontend && npm test`** — new tests fail (module missing).
- [ ] **Step 3: Implement the three functions.**
- [ ] **Step 4: `npm test`** — all pass.
- [ ] **Step 5: Commit** `feat(stock): AI read reducer, thesis split and tab mapping`

### Task 6: Stock page — AI card on top, Details tab (`frontend/src/...`)

**Files:**
- Create: `frontend/src/components/stock/AiRead.jsx`, `frontend/src/components/stock/DetailsTab.jsx` (from
  `AnalysisTab.jsx` minus the AI panel and the `requestAi` effect; delete `AnalysisTab.jsx`)
- Modify: `frontend/src/components/stock/useStockAnalysis.js`, `frontend/src/pages/Stock.jsx`,
  `frontend/src/components/stock/NewsTab.jsx` (`onAnalysis` -> scroll to the AI card)

**Interfaces:**
- Consumes: Task 5 `aiReducer`, `AI_EMPTY`, `splitThesis`, `stockTab`; Task 4 frames and note endpoint.
- Produces: `useStockAnalysis(symbol) -> { quick, ai, aiRead, retryAi, reloadQuick }` where `aiRead` is the
  reducer state and `ai = { data: aiRead.read, loading: aiRead.loading && !aiRead.read, error: aiRead.error }`
  (today's shape for `NewsTab`/`EventsTab`).

- [ ] **Step 1: Hook** — on mount and on symbol change: dispatch `reset`, `stream.request('analyze', {symbol},
  (m) => dispatch({symbol, event: m.event, data: m.data}))`; cancel on cleanup. No socket (`!request.ok`): GET
  `endpoints.stockNote(symbol)` -> dispatch `cached` with `{read, at, stale}` (404 -> `{read:null, stale:true}`);
  if stale, POST `endpoints.analyze(symbol)` -> `report` / `error`. `retryAi` re-sends.
- [ ] **Step 2: `AiRead.jsx`** — the five states in the spec's card table, title "AI read", `AiMarkdown` for the
  summary (collapsed ~3 lines, "Read more" expands and shows the thesis from `splitThesis`), sentiment label/score
  from `read.sentiment`, footer "Based on N articles · as of HH:MM" (`read.sentiment.relevant_count`,
  `formatDateTime(at)`), "Updating…" chip while `stale && !error`, stage copy "Reading N headlines…" /
  "Writing the note…", Retry via `ErrorLine onRetry={retryAi}`. Root element gets `id="ai-read"`.
- [ ] **Step 3: `Stock.jsx`** — remove the `note` read and `noteText` strip; render `<AiRead …/>` after the position
  block; tabs `chart | news | details | events` with `stockTab` applied to the tab param; "Set one in Analysis"
  -> "Set one in Details" (`setTab('details')`); `NewsTab onAnalysis={() => document.getElementById('ai-read')?.scrollIntoView({behavior:'smooth'})}`.
- [ ] **Step 4: `npm run lint && npm test && npm run build`** — clean, all pass, build OK.
- [ ] **Step 5: Commit** `feat(stock): AI read card on top, refreshed and streamed on every open; Details tab`

### Task 7: Docs

**Files:**
- Modify: `docs/wiki/frontend.md` (Stock flow), `docs/wiki/data-ai-jobs.md` (analyst cache keys, staleness, sink,
  socket frames), `frontend/src/handbook/ai-and-news.md` (how the stock AI read runs); set `verified_at` on both wiki
  pages to the last code commit.

- [ ] **Step 1: Update the three docs** to the shipped names (`latest`, `analyst:last:*`, `stream_completion`,
  `report_sink`, frames, `AiRead`, `DetailsTab`).
- [ ] **Step 2: `python3 docs/wiki/stale.py`** — expected `wiki current at <sha>`; handbook test:
  `cd frontend && npm test` passes.
- [ ] **Step 3: Commit** `docs: stock page AI read, analyst last read and streaming`

## Waves (parallel execution)

- Wave 1: Task 1, Task 2, Task 5 (no shared files).
- Wave 2: Task 3 (needs 1, 2), Task 6 (needs 5; codes against Task 4's frame contract above).
- Wave 3: Task 4 (needs 1, 3).
- Then Task 7, full pytest + frontend checks, one final review, deploy (backend + ingest + jobs; Vercel on push).
