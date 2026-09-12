# Phase 7 — multi-worker readiness — design

Status: approved by user 2026-09-12, pending implementation plan.

## Goal

ROADMAP.md Phase 7 asks the backend to survive more than one Uvicorn worker process on
this host. Four coupled problems currently assume a single process: the WS hub's in-memory
fan-out, the scheduler's unguarded daily pass, the trading-run registry's process-local
`_RUNS` dict, and the LLM singleton's process-local model cache (plus a genuinely dead
per-user model preference, discovered during investigation — see below).

Investigation before this design found two of the four ROADMAP bullets were less literal
than their wording suggests:

- The LLM "singleton" is already stateless-per-call for model construction
  (`components/chat/agent.py`'s own comment: "Built fresh per call, not cached on self").
  What's actually broken is narrower: `backend/app_settings.py`'s `_cached_llm_model` is a
  process-local cache of the admin-set deployment-wide model, refreshed only on a local
  write — a second worker keeps serving the old model until it restarts.
- The per-user `omniroute_model` preference (`backend/prefs.py`) is saved via
  `PUT /settings/preferences` but is not read anywhere. Wiring it up is a real feature
  (thread a per-user model choice into LLM call sites), not itself a multi-worker fix — the
  user asked for it to be included in this phase anyway (see Non-goals for what's
  deliberately excluded from that expansion).

## Non-goals

- **No sticky request routing / per-worker port mapping.** Uvicorn's `--workers N` binds
  every worker to the same port via `SO_REUSEPORT`; the OS load-balances connections with no
  visibility into which worker gets which request. Cross-worker correctness is solved with
  Redis (already a deployment dependency — Upstash Redis, used by sentiment/analyst-verdict
  caches, kill-switch, broker session stores), not by making requests sticky.
- **No leader-elected price pump.** Each worker keeps polling its own locally-watched
  symbols independently (`backend/ws/pump.py` unchanged internally). Two workers both
  watching the same symbol poll it twice — an accepted, documented cost at this app's
  current scale (a personal deployment, not a scan of hundreds of concurrent users), not a
  defect this phase fixes. A future fix would need a cross-worker "who's watching what"
  registry; explicitly deferred.
- **No auth added to `/chat/message` or `/analyze/{symbol}`.** Both are pre-existing
  unauthenticated HTTP routes with no `Depends(get_current_user)` — the real per-user
  interactive paths are the WS-routed `_stream_chat`/`_stream_analysis` handlers
  (`backend/ws/routes.py`), which already carry `connection.user_id`. The two legacy HTTP
  routes stay on the deployment-wide default model; adding auth to them is a separate,
  security-relevant change out of scope here.
- **No per-user model for the scheduler's shared analyst-verdict/sentiment refresh.**
  `refresh_analyst_verdict`/`refresh_sentiment` compute one cached value per symbol, shared
  across every user's scan (`backend/ai/analyst_verdict.py`'s own docstring: "shared across
  every user's scan, never per-user") — there is no single user whose preference would
  apply. Unaffected by the per-user model work; stays on the deployment default.
- **No confirmation round-trip for cross-worker run cancellation.** The stop broadcast (see
  Architecture §5) is fire-and-forget, matching the app's existing best-effort delivery style
  (`Connection.offer()` already drops rather than blocks on backpressure). A confirmed
  request/response over Redis would need a correlation id, a response channel, and a
  timeout — real complexity for a failure mode (a stop that silently misses its target) that
  self-heals: the run either shows up as still RUNNING on next check, or the daily restart
  clears it.

## Architecture

### 1. Shared cross-worker event bus (new)

New `backend/broadcast.py`: a thin wrapper over Redis pub/sub providing `publish(channel:
str, payload: dict)` and a background `listen(redis, handlers: dict[str, Callable])` task
that subscribes once and dispatches each received message to the handler registered for its
channel. Started once at app startup (`server.py`, alongside `scheduler.start`/`pump.start`)
and given the two handlers §2 and §5 need.

When `redis` is `None` (tests, local dev without Redis) `publish` is a no-op and callers fall
back to direct in-process delivery — the same "degrade, don't crash" posture
`get_cached_sentiment`/`get_cached_verdict` already established for a missing cache.

This is a mutex-free broadcast primitive; the scheduler's lock (§4) is a separate mechanism
(mutual exclusion, not fan-out) and does not use this module.

### 2. WS hub fan-out (`backend/ws/hub.py`)

`Hub.publish()` no longer iterates local `_connections` directly. Instead it always calls
`broadcast.publish("ws:events", message)`. Every worker's subscriber (registered in §1's
`listen()` handler map under `"ws:events"`) receives every published message — including the
one it just sent — and performs the actual local delivery (the existing `for connection in
list(self._connections): ...` loop moves here, into the handler, taking `message` as input
rather than being inlined in `publish`). This unifies local and cross-worker delivery into
one code path: a message is never delivered by the caller directly, only by the subscriber
loop, whether that loop lives in the same process or a different one.

`subscribed_symbols()`, `users_on()`, `users_watching()` stay local-only (introspection over
`self._connections`, unchanged) — per the resolved pump design (§3), nothing needs a
cross-worker view of who's watching what.

### 3. Price pump (`backend/ws/pump.py`)

No code changes. `push_once` already calls `hub.publish(...)`, which is now cross-worker
correct by construction (§2) — a price tick or P&L update computed by worker A reaches a
browser connected to worker B automatically. Each worker's `pump_loop` keeps running
independently and keeps polling only its own `hub.subscribed_symbols()`; two workers with
overlapping watchers issue overlapping `mark_prices` calls. Documented in ROADMAP as a known,
accepted cost (see Non-goals).

### 4. Scheduler distributed lock (`backend/scheduler.py`)

New: before `run_daily_jobs`'s body executes inside `scheduler_loop`, acquire a Redis lock —
`SET "scheduler:daily_lock" <owner-token> NX PX <ttl_ms>` — skipping the pass entirely
(logging and continuing the loop, not erroring) if the lock is already held. TTL sized
generously (2 hours) to cover the full pass, including per-user LLM calls, rather than a
heartbeat/renewal loop: simpler, and a crashed holder self-heals at TTL expiry instead of
leaving the pass permanently blocked. Released explicitly (`DEL` guarded by owner-token
match, so a worker never releases a lock some other worker has since acquired after this
one's TTL expired) in a `finally` once the pass completes. When `redis is None` (tests), the
lock is skipped entirely and the pass always runs — matches every existing test's
`redis=None`/mocked-redis calling convention for `run_daily_jobs`.

### 5. Cross-worker run cancellation (`backend/routers/trading.py`)

No change to `/trading/stop`'s ownership check — `RunStore.get(run_id)` already reads Mongo,
which is already cross-worker-correct today. Only `stop_background_run(run_id)` gains a
fallback: if `run_id` is not in this worker's local `_RUNS`, it calls
`broadcast.publish("runs:cancel", {"run_id": run_id})` and returns `True` (optimistic — the
caller already confirmed via `RunStore` that the run is genuinely `ACTIVE`, so "some worker
holds this task" is the only remaining possibility besides an already-dead task whose
`RunStore` row just hasn't caught up yet, an existing race this phase doesn't newly
introduce). Every worker registers a `"runs:cancel"` handler (§1) that checks its own local
`_RUNS` for the given `run_id` and cancels it if present — reusing the exact cancel-and-await
logic `stop_background_run` already has for the local case. The task's existing
`add_done_callback(_cleanup)` (unchanged) marks it stopped in `RunStore` and pops it from
`_RUNS` regardless of whether the cancellation was requested locally or via broadcast.

### 6. LLM singleton

**Deployment-wide model cache** (`backend/app_settings.py`): `current_llm_model()` changes
from "return the cached value, refreshed only when `set_llm_model` runs in this process" to a
short-TTL re-read: cache the Mongo-read value in-process for 30 seconds, then re-fetch on the
next call past that window. `current_llm_model()` must become `async` to read Mongo directly
(it's called from `LLMService.get_llm()`, which is synchronous today — see below for how that
threads through). No pub/sub involved; this is a plain TTL cache, deliberately decoupled from
§1's broadcast bus since a 30-second staleness window on an admin setting change needs no
real-time push.

**Per-user model — ambient override via `contextvars`, not parameter-threading.** A naive
`model: Optional[str] = None` parameter would need to thread through 8 functions across 5
files: `ResearchAgent.run` → `resolve_node` → `resolve_company_query`
(`master/search.py::_find_peers`) → `resolve_symbol`/`_llm_pick`
(`instruments/resolve.py`) → `analyst_node` → `AnalystAgent.analyze` →
`analyze_sentiment_logic`/`_analyze_one` (`analyst/sentiment.py`, one LLM call per article,
`asyncio.gather`ed) and `classify_events_logic` (`analyst/events.py`) → `synthesize_node`'s
own thesis call. Several of those (`resolve_symbol`, `analyze_sentiment_logic`,
`classify_events_logic`) are also called from unrelated non-per-user contexts
(`research/quick.py`, `components/master/stock_info.py`, the scheduler's shared refresh) that
would gain a parameter they never pass. Rejected as unnecessarily invasive for what's meant
to be an ambient "which model is this request using" setting.

Instead: `backend/llm.py` gains a module-level `_model_override:
contextvars.ContextVar[Optional[str]] = ContextVar("model_override", default=None)` and a
context manager `use_model(model: Optional[str])` that sets it for the duration of a `with`
block (a no-op when `model` is `None`, so callers with no preference don't need to branch).
`LLMService.get_llm()` becomes `model = _model_override.get() or await
current_llm_model()`. Because `current_llm_model()` becomes async (previous paragraph),
`get_llm()` becomes async too — its two call sites (`get_completion` internally, and
`components/chat/agent.py`'s direct `llm_service.get_llm()` call inside `_build_agent`, which
becomes `async def`) both already run in an async context, so this is a mechanical `await`
addition. `ChatAgent.processed_message` also calls `_build_agent()` but has no callers
anywhere in the codebase today (confirmed by grep) — it picks up the `await` mechanically,
dead code otherwise, out of scope to extend further.

`contextvars.ContextVar` values propagate correctly into code the current task awaits
directly, and into new `asyncio.Task`s created via `asyncio.create_task`/`asyncio.gather`
from within the `with use_model(...)` block, because each new Task captures a copy of the
current context at creation time — this covers `analyze_sentiment_logic`'s per-article
`asyncio.gather(*(_analyze_one(...) for article in articles))` fan-out correctly with no
changes to that function. **No signature or call-site changes are needed anywhere in
`ResearchAgent`, `AnalystAgent`, `analyst/sentiment.py`, `analyst/events.py`,
`master/search.py`, or `instruments/resolve.py`** — every nested `llm_service.get_completion`
call in the whole tree picks up the override transparently.

`with use_model(model):` wraps the entry point at the three real per-user call sites (fetched
once, not re-fetched per nested LLM call):
- `backend/ws/routes.py`'s `_stream_chat`/`_stream_analysis` — as the first line of each
  handler, read `connection.user_id`, fetch `await PrefsStore(db.db).get(user_id)`, and enter
  `with use_model(prefs.get("omniroute_model")):` around the rest of the handler body. Since
  both are already dispatched via `asyncio.create_task(...)` from the WS message loop
  (`backend/ws/routes.py`), setting the override as the first statement *inside* the task body
  is sufficient — no change needed at the `create_task(...)` call sites themselves.
- `backend/suggestions/thesis.py`'s `attach_theses(db, user_id, ...)` — already has `user_id`
  in scope; same `PrefsStore` lookup, `with use_model(...):` wraps the per-suggestion loop
  (fetched once per call, not once per suggestion).

Every other call site (the scheduler's shared analyst-verdict/sentiment refresh, the two
legacy unauthenticated HTTP routes) never enters a `with use_model(...)` block, so
`_model_override.get()` returns the default `None` and `get_llm()` falls through to
`current_llm_model()` unchanged.

## Testing

- `backend/broadcast.py`: unit tests with a mocked Redis pub/sub client — `publish` calls
  `redis.publish`, `listen` dispatches a received message to the correct handler by channel,
  an unmocked/`None` redis makes `publish` a no-op.
- `ws/hub.py`: existing direct-delivery tests adapt to call the new local-delivery handler
  function directly (simulating "a message arrived from the bus") rather than `Hub.publish`
  performing delivery itself; one new test confirms `Hub.publish` calls
  `broadcast.publish` rather than iterating connections when a redis is configured.
- `scheduler.py`: new tests for lock acquisition (mocked redis) — a second `run_daily_jobs`
  call while the lock is held is skipped (returns early / no-ops), lock is released after
  completion (`redis.delete` called with the right key), `redis=None` always runs the pass
  (matches every existing scheduler test's calling convention).
- `trading.py`: new tests for `stop_background_run`'s broadcast fallback — `run_id` not in
  local `_RUNS` triggers `broadcast.publish("runs:cancel", ...)`; the `"runs:cancel"` handler
  cancels a matching local task and leaves a non-matching `run_id` alone.
- `app_settings.py`: TTL-cache tests — two reads within the TTL window hit Mongo once; a read
  after the TTL elapses (fake clock or monkeypatched time) re-fetches.
- `llm.py`: existing tests updated for the now-async `get_llm`. New tests: inside a
  `with use_model("some/model"):` block, `get_llm()` uses that value verbatim instead of
  `current_llm_model()`'s; outside any such block (or with `use_model(None)`), it falls
  through to `current_llm_model()` unchanged; nested/re-entrant `use_model` blocks restore
  the outer value on exit (context manager, not a bare `set()`); a value set in a parent task
  is visible inside a child task spawned via `asyncio.create_task`/`gather` from within the
  `with` block (the actual mechanism `analyze_sentiment_logic`'s per-article fan-out relies
  on) — this is the one test that would have caught a wrong ContextVar propagation
  assumption, so it's required, not optional polish.
- `ws/routes.py`/`thesis.py`: new tests confirming the per-user `PrefsStore` lookup happens
  and `use_model(...)` is entered with its `omniroute_model` value before the LLM-touching
  work runs, and that a user with no preference set (`None`) is a no-op
  (`current_llm_model()`'s value still applies). No changes expected to any existing test in
  `ResearchAgent`/`AnalystAgent`/`analyst/sentiment.py`/`analyst/events.py`/
  `master/search.py`/`instruments/resolve.py` — confirming that is itself part of this task's
  verification (the whole point of the contextvars design is that these files don't change).

## Done when

- The backend runs with two Uvicorn workers and a user connected to one sees live updates
  (price ticks, P&L, run start/stop, suggestions) produced by the other.
- Two workers running `scheduler_loop` concurrently produce exactly one daily pass, not two.
- A trading run started via one worker can be stopped via a request that lands on the other.
- An admin's deployment-wide model change is visible to every worker within the TTL window,
  without requiring a restart.
- A user's saved `omniroute_model` preference actually changes which model answers their chat
  messages, their on-demand analysis requests, and their suggestion theses.
- Full backend suite passes.
