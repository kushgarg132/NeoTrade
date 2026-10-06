# Handbook and Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin-only in-app handbook (`/system`, markdown + live status panels) and an editable backlog (`/system/future`).

**Architecture:** Handbook text is markdown in the repo, bundled with Vite `?raw` and rendered by the existing `Markdown` component, split on `<!-- live:x -->` markers into live panels fed by one admin endpoint `GET /system/status`. Jobs record last runs in Redis through one `mark()` helper. The backlog is a Mongo collection behind admin CRUD routes.

**Tech Stack:** FastAPI, Motor/Mongo, Redis, pytest + mongomock_motor + `backend/tests/test_datalayer_news.FakeRedis`; React 19, Vite, `marked`, vitest.

**Spec:** `docs/superpowers/specs/2026-10-06-handbook-and-backlog-design.md`

## Global Constraints

- Every new route uses `Depends(require_admin)` (`backend/auth/dependency.py:31`); frontend routes redirect non-admins (`user?.role !== 'admin'`) to `/settings`.
- New backend package: `backend/system/` (`__init__.py`, `jobs.py`, `status.py`, `backlog.py`, `seed_backlog.py`, `router.py`); router registered in `backend/server.py` beside `settings_router` with `prefix=settings.API_PREFIX, tags=["System"], dependencies=[Depends(get_current_user)]`.
- Redis key for job records: `job:last:<name>`, hash fields `at` (UTC ISO), `ok` ("1"/"0"), `note` (≤ 2000 chars), no TTL.
- Status response cached 30 s per worker; each block computed independently, a raising block becomes `{"error": "<ExcType>: <msg>"}`.
- Backlog enums: area `System, Data, Trading, AI, News, Journal, UI, Ops, Product`; status `idea, next, doing, done, dropped`; effort `S, M, L` or null. Lengths: title 1–140, why ≤ 2000, notes ≤ 4000, source ≤ 140.
- Secret **locations** only in handbook text, never values.
- Commits end with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line; deploy mode this session is direct (`[skip ci]` on HEAD subject).

## Review Focus

- A Redis or Mongo outage during `/system/status` → every block shows its own error, page still renders (Task 2 test `test_status_block_failure_is_isolated`).
- `mark()` raising inside the daily pass or a loop → the job still completes (Task 1 test `test_mark_failure_never_breaks_the_job`).
- Backlog PATCH with an unknown id or malformed ObjectId → 404, not 500 (Task 3 test `test_patch_unknown_or_bad_id_is_404`).
- Markdown with a marker naming an unknown panel, or no markers → text renders, unknown marker dropped (Task 5 vitest).
- Non-admin opening `/system` or `/system/future` directly → redirected, and the API answers 403 (Tasks 2–3 tests; Task 5 route guard).

---

### Task 1: Job last-run records

**Files:**
- Create: `backend/system/__init__.py`, `backend/system/jobs.py`
- Modify: `backend/scheduler.py` (`_run_locked`), `backend/guardrails/monitor.py:166-171`, `backend/engine/paper_orders.py:156-168`, `backend/engine/autorun.py:355-362`, `backend/guardrails/telegram_bot.py:481-488`
- Test: `backend/tests/test_system_jobs.py`

**Interfaces:**
- Produces: `async def mark(redis, name: str, ok: bool, note: str = "") -> None` (swallows and logs every exception); `async def last_runs(redis, names: list[str]) -> dict[str, dict | None]` returning `{name: {"at": str, "ok": bool, "note": str} | None}`; constants `DAILY_PASS = "daily_pass"`, `LOOPS = ("guardrail_monitor", "paper_orders", "autorun", "telegram")`.

- [ ] **Step 1: Write failing tests** — `test_mark_writes_the_record` (mark then last_runs returns ok True, note, ISO `at`); `test_last_runs_missing_is_none`; `test_mark_failure_never_breaks_the_job` (redis whose `hset` raises → `mark` returns None, no raise); `test_daily_pass_records_success_and_failure` (monkeypatch `scheduler.run_daily_jobs` to return `{"created": 2}` then to raise `RuntimeError("boom")`; call `_run_locked(db, FakeRedis())` with `LAST_PASS_KEY` unset; record ok True with note containing `"created": 2`, then ok False with note containing `boom`, and the exception still propagates).
- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_system_jobs.py -q` — expect FAIL (module missing).
- [ ] **Step 3: Implement** `jobs.py`; in `_run_locked` wrap the `run_daily_jobs` call: on success `mark(redis, DAILY_PASS, True, json.dumps(result, default=str))`, on exception `mark(..., False, f"{type(e).__name__}: {e}")` then re-raise. Add `await mark(redis, "<loop name>", True)` once per tick in the four loops (after the tick's work, before sleep; in `except` branches `ok=False` with the error text). Loops that don't hold `redis` get it from `backend.database.db.redis`. Check FakeRedis supports `hset`/`hgetall`; extend it in `test_datalayer_news.py` if not.
- [ ] **Step 4: Run** the new tests plus `tests/test_scheduler*.py tests/test_guardrail* tests/test_paper_orders* tests/test_autorun* tests/test_telegram_bot.py` — all PASS.
- [ ] **Step 5: Commit** `feat(system): jobs record their last run`.

### Task 2: Live status endpoint + GIT_SHA

**Files:**
- Create: `backend/system/status.py`, `backend/system/router.py`
- Modify: `backend/server.py` (include router), `backend/Dockerfile` (`ARG GIT_SHA` + `ENV GIT_SHA=$GIT_SHA` before `COPY . ./backend`), `docker-compose.yml` (`backend.build.args: GIT_SHA: ${GIT_SHA:-}`)
- Test: `backend/tests/test_system_status.py`

**Interfaces:**
- Consumes: Task 1 `last_runs`, `DAILY_PASS`, `LOOPS`; `backend.datalayer.worker.heartbeat_ages(redis)`; `backend.runs.ALIVE_KEY`; `backend.scheduler.seconds_until_next_run(now)`; `backend.routers.settings.fetch_usage()`; settings `NEWS_LLM_CALLS_PER_DAY`, `PLAN_LLM_CALLS_PER_DAY`; keys `news:deep_calls:<IST date>`, `plan:calls:<IST date>`.
- Produces: `GET /api/v1/system/status` → `{"as_of": str, "deploy": {...}, "jobs": {...}, "news": {...}, "data": {...}, "ai": {...}}` with fields exactly as the spec §2 table; `async def build_status(db, redis) -> dict`; module `STARTED_AT` set at import.

- [ ] **Step 1: Write failing tests** — `test_status_shape` (mongomock + FakeRedis seeded with a `job:last:daily_pass`, a `news_items` doc, `news:deep_calls:<today>`=3; assert top-level keys, `jobs.daily_pass.ok is True`, `ai.news_calls_today == 3`, `deploy.backend_sha` equals monkeypatched env `GIT_SHA`); `test_status_block_failure_is_isolated` (monkeypatch the news block builder to raise → `news == {"error": ...}`, other blocks intact); `test_status_is_admin_only` (non-admin 403); `test_status_is_cached_30s` (two calls, builder called once).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** one `async def _<block>(db, redis) -> dict` per block, gathered with `asyncio.gather(..., return_exceptions=True)` and mapped to `{"error": ...}`. `data.collections` lists: `users, journal_trades, paper_trades, paper_positions, suggestions, portfolio_snapshots, news_items, instruments, backlog` (counts via `estimated_document_count`; a missing collection reads 0). `dbStats` via `db.command("dbStats")`; Redis `dbsize()` and `info("memory")["used_memory_human"]` (both guarded, FakeRedis may lack them → the block's own error). `ai.usage` from `fetch_usage()` or its `UsageUnavailable.detail`.
- [ ] **Step 4: Run** the tests — PASS; `docker compose config` shows the build arg.
- [ ] **Step 5: Commit** `feat(system): admin status endpoint and GIT_SHA in the image`.

### Task 3: Backlog API

**Files:**
- Create: `backend/system/backlog.py` (store + Pydantic models), routes in `backend/system/router.py`
- Test: `backend/tests/test_system_backlog.py`

**Interfaces:**
- Produces: `GET /api/v1/system/backlog` → `{"items": [item...]}` sorted by status order (doing, next, idea, done, dropped) then `rank`; `POST` body `{title, area, status?="idea", why?, notes?, effort?, source?}` → item (rank = max rank in status + 1); `PATCH /{id}` partial body incl. `rank` → item; `DELETE /{id}` → `{"ok": true}`. Item JSON: all spec §3 fields plus `id` (str).

- [ ] **Step 1: Write failing tests** — `test_create_list_patch_delete`; `test_validation_422` (empty title, title 141 chars, area "Foo", status "later"); `test_done_at_stamped_and_cleared`; `test_patch_unknown_or_bad_id_is_404` (valid-looking unknown ObjectId and `"nope"`); `test_backlog_is_admin_only` (each route 403 for a non-admin).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with `Literal` enums and `Field(min_length/max_length)`; `updated_at` on every write; `done_at` set when status becomes done, unset when it leaves done.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(system): editable backlog API`.

### Task 4: Backlog seed

**Files:**
- Create: `backend/system/seed_backlog.py` (`SEED: list[dict]`, `async def seed(db) -> int` returning inserted count, `__main__` connects via `backend.database.db.connect_to_database()`)
- Test: `backend/tests/test_system_backlog.py::test_seed_is_idempotent`

- [ ] **Step 1: Write failing test** — seed twice → second returns 0, collection count == `len(SEED)`, every doc has non-empty `source`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Compile `SEED`** by reading `docs/ROADMAP.md` (Phases 5b+ open, 12, 13 and every "not done / deferred" list), the claude-mem work state lists `neotrade-audit-fixes` (open_from_audit, skipped, user_todo), `shared-platform-extraction` (items 3–6), and this session's leftovers: news ingest tags market-wide stories to single symbols; verify AI plan prose has no snake_case after 8faab51; warm the gateway usage cache at startup. Upsert by `title` with `$setOnInsert`; ranks in list order per status.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(system): seed the backlog from open roadmap and audit items`.

### Task 5: Handbook page (frontend)

**Files:**
- Create: `frontend/src/utils/handbook.js` (`splitLive(md: string, known: string[]) -> Array<{md: string} | {live: string}>`), `frontend/src/utils/handbook.test.js`, `frontend/src/pages/Handbook.jsx`, `frontend/src/components/system/LivePanels.jsx` (`<LivePanel name status />` for deploy, jobs, news, data, ai), `frontend/src/components/system/RequireAdmin.jsx`
- Modify: `frontend/src/App.jsx` (`/system` → Handbook, `/system/future` → Backlog from Task 6; both wrapped `gated(<RequireAdmin>…)`), `frontend/src/utils/api.js` (`endpoints.system = { status: '/system/status', backlog: '/system/backlog', item: (id) => \`/system/backlog/${id}\` }`), `frontend/vite.config.js` (`define: { 'import.meta.env.VITE_GIT_SHA': JSON.stringify(process.env.VERCEL_GIT_COMMIT_SHA || '') }`), `frontend/src/pages/Settings.jsx` About tab
- Delete: `frontend/src/pages/SystemArchitecturePage.jsx`

- [ ] **Step 1: Decide markdown location** — via Vercel MCP `get_project` on `neotrade`, read `rootDirectory` and `sourceFilesOutsideRootDirectory`. If true, import `../../../docs/handbook/<slug>.md?raw`; else files go in `frontend/src/handbook/` and `docs/handbook/README.md` points there. Create the five files with a one-line heading and their markers as placeholders (content is Task 7).
- [ ] **Step 2: Write failing vitest** — `splitLive` cases: no markers → one `{md}`; `a\n<!-- live:jobs -->\nb` → `[{md:'a\n'},{live:'jobs'},{md:'\nb'}]`; unknown `<!-- live:foo -->` dropped, text kept; marker at file start/end yields no empty `{md}`.
- [ ] **Step 3: Run** `cd frontend && npx vitest run src/utils/handbook.test.js` — FAIL.
- [ ] **Step 4: Implement** `splitLive`, `Handbook` (Tabs System & Data · Trading & Money · AI & News · Jobs & Ops · Journey · Future-link, `useTab`, one status fetch per mount and on `visibilitychange`), `LivePanels` (Sheet + Statement rows, "as of", `{error}` → "Unavailable: <error>", missing backend SHA → "unknown (built without GIT_SHA)"), `RequireAdmin` (`Navigate to="/settings"` when `user.role !== 'admin'`), About tab: admins get Handbook + Future links, others the one line from the spec.
- [ ] **Step 5: Run** vitest, `npx eslint src`, `npm run build` — PASS, 0 errors.
- [ ] **Step 6: Commit** `feat(system): handbook page with live panels; About links`.

### Task 6: Backlog page (frontend)

**Files:**
- Create: `frontend/src/pages/Backlog.jsx`

**Interfaces:**
- Consumes: Task 3 API; `endpoints.system.backlog/item` from Task 5.

- [ ] **Step 1: Implement** — groups Doing, Next, Ideas open; Done, Dropped in `<details>`; area chips (All + 9 areas); quick add (title input + area select, Enter submits); tap item → inline editor for why, notes, effort, status (save on blur/change); ↑/↓ swap `rank` with the neighbour via two PATCHes; delete = first tap arms "Delete?" for 3 s, second tap deletes. Optimistic updates roll back on error and show `err.response.data.detail`.
- [ ] **Step 2: Run** `npx eslint src && npm run build` — PASS.
- [ ] **Step 3: Commit** `feat(system): editable backlog page`.

### Task 7: Handbook content and doc moves

**Files:**
- Modify: the five handbook markdown files; `docs/ARCHITECTURE.md` (becomes a pointer); `.claude/CLAUDE.md` ("Read these" row + the file:line-anchors rule → `docs/handbook/`); `PRODUCT.md` (`§1.2` link → handbook section; surfaces table rows for Handbook and Future); every other `grep -rn "ARCHITECTURE.md" --include=*.md --include=*.py --include=*.jsx` hit outside `docs/superpowers/` (dated specs/plans stay as written).

- [ ] **Step 1: Write content** per spec §1 outline from `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, specs and `git log`; move every ARCHITECTURE.md section into exactly one handbook file, keeping its file:line anchors and re-checking each against the code; place markers: `live:deploy` and `live:data` in system-and-data, `live:ai` and `live:news` in ai-and-news, `live:jobs` in jobs-and-ops. Journey: dated milestones (git month counts: 2025-11 4, 2025-12 34, 2026-01 3, 2026-09 246, 2026-10 326), each pivot's reason and lesson.
- [ ] **Step 2: Verify** — `grep -rn "file:line\|:[0-9]\+" docs/handbook | head` spot-check five anchors against the code; `grep -rn "ARCHITECTURE.md"` shows only the pointer file and dated docs; `grep -rniE "secret|password|token" docs/handbook` shows no values.
- [ ] **Step 3: Run** `npm run build` (content is bundled) — PASS.
- [ ] **Step 4: Commit** `docs: handbook replaces ARCHITECTURE.md`.

### Task 8: Ship

**Files:**
- Modify: `/home/ubuntu/projects/ci-workflows/.github/workflows/deploy-backend.yml` (env `GIT_SHA: ${{ inputs.sha }}` on the compose build step), `/home/ubuntu/CLAUDE.md` + `/home/ubuntu/docs/host/push-to-deploy.md` (direct deploy: `GIT_SHA=$(git rev-parse HEAD) docker compose build backend`)

- [ ] **Step 1:** Full backend suite `cd backend && python -m pytest -q` (background) and frontend `npx vitest run && npm run build` — all PASS.
- [ ] **Step 2:** Push NeoTrade (HEAD `[skip ci]`), commit + push ci-workflows and the home repo docs.
- [ ] **Step 3:** Deploy clone `git pull --ff-only`, `GIT_SHA=$(git rev-parse HEAD) docker compose build backend && docker compose up -d backend`; run `docker exec neotrade-backend python -m backend.system.seed_backlog` → prints inserted count.
- [ ] **Step 4:** Verify — `/api/v1/system/status` as admin returns every block without `error` (or a stated reason) and `deploy.backend_sha` = HEAD; Vercel deployment READY for HEAD; screenshots at 390 px and 1440 px of `/system` (each tab) and `/system/future`; fix what they show in one batch.
