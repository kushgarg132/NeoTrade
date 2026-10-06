# Handbook and backlog — design

2026-10-06. Status: approved in conversation, awaiting spec review.

## Intent

The operator (the only admin, also the developer) wants one place inside the app
that explains how all of NeoTrade works — architecture, data, trading, AI, news,
jobs, ops, and how it got here — as a **reference handbook for himself**, plus
an **editable backlog** of future enhancements.

Said by the user:
- Audience: "Me, as reference" — dense, module paths, every system.
- Freshness: hand-written explanations **plus live status** from the backend.
- Sections: System + Data, Trading + Money, AI + News, Jobs + Ops; a Journey of
  milestones and pivots (Claude drafts from git/ROADMAP/specs, user corrects).
- Future page: an **editable backlog** stored in Mongo.
- Approach A: markdown handbook in the repo, rendered in-app, with live panels.

Assumed (stated in conversation, not objected to):
- Both pages are **admin-only**: they show infra detail (host, secret file
  locations, collection sizes). Non-admins lose `/system`.
- Scheduler jobs get a new last-run record; nothing records one today.

Success: the user can answer "how does X work, where is it, and is it running
right now?" from the app, and keep a living list of what comes next.

## 1. Pages, routes, content

### `/system` — Handbook (admin-only)

Tabs: **System & Data · Trading & Money · AI & News · Jobs & Ops · Journey**,
plus a **Future** tab that links to `/system/future`. The selected tab sits in
the URL (`?tab=`, existing `useTab` hook).

Each tab renders `docs/handbook/<slug>.md`:

| Tab | File |
|---|---|
| System & Data | `docs/handbook/system-and-data.md` |
| Trading & Money | `docs/handbook/trading-and-money.md` |
| AI & News | `docs/handbook/ai-and-news.md` |
| Jobs & Ops | `docs/handbook/jobs-and-ops.md` |
| Journey | `docs/handbook/journey.md` |

- Imported at build time with Vite `?raw` from `../../docs/handbook/` relative
  to the frontend. Vercel builds with Root Directory `frontend`, so the plan's
  first task verifies files outside it are present at build (Vercel's
  "include files outside root directory" setting, on by default for git
  deploys). If they are not, the markdown lives in `frontend/src/handbook/`
  and `docs/handbook/README.md` points there; either way there is one copy.
- Rendered with the existing `components/common/Markdown.jsx` (`marked` +
  DOMPurify).
- A line `<!-- live:<panel> -->` in the markdown marks where a live panel
  renders. A pure function `splitLive(markdown) -> [{md}|{live: name}]` splits
  the file; GitHub shows the comment as nothing.
- Content is written from code, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
  `docs/superpowers/specs/*`, and git history, naming module paths. Secret
  **locations** only, never values.

Content outline:
- **System & Data** — host (Oracle VM, Nginx + Let's Encrypt on nip.io),
  containers (`neotrade-backend` 2 uvicorn workers, `neotrade-ingest`), Vercel
  frontend, MongoDB Atlas, Upstash Redis, OmniRoute; market data sources and
  fallback order; broker adapter matrix (Kite / Upstox / Angel One); Mongo
  collections and what each holds; Redis key families; instrument master.
  Panels: `live:deploy`, `live:data`.
- **Trading & Money** — the three kinds of money (Mine `mine`, AI `ai`,
  Practice/paper) and how they stay apart; price bar → signal → sized trade →
  proposal/fill; registered strategies; conviction formula and the 30% AI cap;
  gates to real money (backtest + paper record); guardrails, kill-switch,
  square-off; autopilot and its fence; decisions inbox.
- **AI & News** — OmniRoute, model per kind of task, fact layer and tool
  runner, grounding check, budgets, chat cards that confirm; news sources,
  triage, scoring, materiality, alerts, symbol tagging. Panels: `live:ai`,
  `live:news`.
- **Jobs & Ops** — daily pass (16:00 IST) and what it runs, the loops
  (guardrail monitor, paper orders, autorun, telegram, ws pump), ingest
  worker loops; deploys (push-to-deploy vs direct `[skip ci]`), auth and
  sessions, token redaction, logs, secrets locations. Panel: `live:jobs`.
- **Journey** — dated milestones from Nov 2025 (AI agent stock investor,
  OpenAI → Gemini) through the Sep 2026 rename, the discipline-layer pivot,
  journal/guardrails/brokers, and the Oct 2026 sprint (accounts split, news
  layer, AI on tools, UI critique passes); each pivot with its reason and the
  lesson (e.g. strategies failing their backtest gate).

### `/system/future` — Backlog (admin-only)

See §3.

### Settings → About

Admins: two links, Handbook (`/system`) and Future (`/system/future`).
Everyone else: one line, "NeoTrade — the discipline layer on top of your
broker." Both routes redirect non-admins to `/settings`.

### Removed / changed

- `frontend/src/pages/SystemArchitecturePage.jsx` deleted; its content moves
  into the handbook files.
- `docs/ARCHITECTURE.md`'s content moves into the handbook files, keeping its
  file:line anchors; the file becomes a short pointer to `docs/handbook/`.
  Its duties move with it: `.claude/CLAUDE.md`'s "Read these" table and its
  "verified against the code with file:line anchors — fix the document in the
  same commit" rule point at `docs/handbook/`; PRODUCT.md's `§1.2` link and
  every other `grep -rn ARCHITECTURE.md` hit (docs, specs, code comments such
  as `SystemArchitecturePage`'s) are repointed to the matching handbook
  section.

## 2. Live status — `GET /api/v1/system/status` (admin-only)

One response, one block per panel. Each block is computed independently; a
failing block returns `{"error": "<reason>"}` and the others still render.
Response cached 30 s per worker.

| Block | Fields | Source |
|---|---|---|
| `deploy` | `backend_sha`, `backend_started_at` | `GIT_SHA` env baked by a new Dockerfile `ARG GIT_SHA`; process start time. Frontend SHA comes from `import.meta.env.VITE_GIT_SHA`, defined in `vite.config` from `VERCEL_GIT_COMMIT_SHA` |
| `jobs` | `daily_pass: {at, took_s, ok, summary | error}`, `next_daily_pass_at`; `loops: {name: {at, ok, note}}` for guardrail_monitor, paper_orders, autorun, telegram; `ingest: {loop: age_s}`; `workers_alive` | new `job:last:<name>` Redis hash via `backend/system/jobs.py mark()`; existing `heartbeat_ages()`; existing worker heartbeat keys; `seconds_until_next_run()` |
| `news` | items in last 24 h by status, newest `published_at`, unscored backlog (NEW + TRIAGED), last material item | `news_items` |
| `data` | `estimated_document_count` for the main collections, Atlas `dbStats` dataSize/storageSize, Redis `dbsize` + `used_memory_human`, connected broker sessions per broker, instrument master count + last refresh | Mongo, Redis `INFO`, existing stores |
| `ai` | `news_calls_today/limit`, `plan_calls_today/limit`, gateway `usage` | `news:deep_calls:<day>` vs `NEWS_LLM_CALLS_PER_DAY`; `plan:calls:<day>` vs `PLAN_LLM_CALLS_PER_DAY`; `fetch_usage()` |

`mark(redis, name, ok, note="")` writes `{at, ok, note}` to `job:last:<name>`
(no TTL). Called: after each daily pass (summary JSON as note, or the
exception text with `ok=False`), and once per tick in the four loops. A
failing `mark` is logged and never breaks the job.

Direct deploy becomes `GIT_SHA=$(git rev-parse HEAD) docker compose build
backend`; docker-compose passes `args: GIT_SHA: ${GIT_SHA:-}`; the shared
`ci-workflows` deploy workflow passes it too (separate repo, separate commit).
Missing SHA renders "unknown (built without GIT_SHA)".

Panels render as compact `Statement` tables in the existing doc style, each
with its "as of" time; the page re-fetches status on tab focus.

## 3. Backlog

Collection `backlog` — app-wide, no `user_id`.

| Field | Type |
|---|---|
| `title` | str, 1–140 |
| `area` | enum: System, Data, Trading, AI, News, Journal, UI, Ops, Product |
| `status` | enum: idea, next, doing, done, dropped |
| `why` | str ≤ 2000 |
| `notes` | str ≤ 4000 |
| `effort` | enum S, M, L, or null |
| `source` | str ≤ 140 (e.g. "ROADMAP Phase 12", "audit 2026-10-05") |
| `rank` | float, ordering within a status |
| `created_at`, `updated_at`, `done_at` | datetimes; `done_at` set on → done, cleared on leaving done |

API (`require_admin`, Pydantic validation, existing rate limits):
`GET /system/backlog`, `POST /system/backlog`, `PATCH /system/backlog/{id}`,
`DELETE /system/backlog/{id}`.

Page: groups Doing → Next → Ideas; Done and Dropped collapsed. Area filter
chips. One-line quick add (title + area, status idea, rank last). Tap an item
to expand and edit why / notes / effort / status in place. Up / down buttons
swap rank with the neighbour in the group. Delete is two taps. Failed writes
roll back the optimistic change and show the API's message.

Seed: `python -m backend.system.seed_backlog` — idempotent (upsert by title),
loads a curated list compiled from ROADMAP open phases (12, 13, 5b+), every
"not done, deliberately / deferred" list, the 2026-10-05 audit's open items,
the shared-platform plan (items 3–6), and this session's leftovers (news
tagger noise, AI plan prose check, usage warm-up at start). Every item names
its `source`. Run once in the backend container after deploy.

## 4. Errors and testing

Backend (pytest, mongomock + the existing FakeRedis):
- status: full shape; one block raising leaves the rest intact; admin-only.
- `mark()`: writes the hash; daily pass records success and failure; a failing
  `mark` does not raise.
- backlog: create / patch / delete; enum and length validation (422);
  `done_at` stamped and cleared; admin-only on every route.
- seed: running twice leaves one copy of each item.

Frontend:
- vitest: `splitLive` splits on markers, keeps text order, ignores unknown
  panels.
- `npm run build` and `eslint` pass; screenshot pass at 390 px and 1440 px on
  prod after deploy.

Docs: PRODUCT.md surfaces table gains the two pages; `~/CLAUDE.md` direct-deploy
line and `docs/host/push-to-deploy.md` gain `GIT_SHA`.

## Out of scope

- Per-task AI call counters beyond the two budgets that exist.
- Drag-and-drop ordering, backlog history, or comments.
- Making the handbook public or non-admin readable.
