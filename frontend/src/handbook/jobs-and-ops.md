# Jobs & Ops

Everything that runs on its own, how code reaches production, and how the doors are locked.

## The daily pass — 4:00 PM IST

`backend/scheduler.py::run_daily_jobs`, once a day on one worker (`scheduler:daily_lock`,
`scheduler:last_pass`), recorded in `job:last:daily_pass`:

1. Expire stale proposals (3 days).
2. Close expired option positions.
3. Refresh analyst verdicts.
4. Long-term scan for every scan-enabled user → proposals, theses, Telegram.
5. Journal sync from every connected broker, then the **broker reconciliation**
   (`backend/engine/broker_recon.py::run_all`, read-only, skipped on a catch-up pass): per user and
   role (`mine`, `ai`), the broker's trades today against the role's ledger book (`<uid>:mine`,
   `<uid>:autopilot`, matched through `live_orders.broker_order_id`) and the journal, and broker
   holdings + positions against the book's open quantities (the AI account must match exactly;
   your own may hold more than the app placed). Mismatches are named `missing_in_ledger`,
   `missing_at_broker`, `quantity_differs`, `price_differs` or `unknown_order` (an AI-account
   order the app never placed). One doc per user/day/role in `broker_reconciliation`, replaced
   on re-run; a logged-out broker is stored as "not checked: logged out". Shown on Today's Do
   today and in the post-close Telegram only when something differs; read at
   `GET /today/reconciliation` (yours) and `GET /system/reconciliation` (admin).
6. Learning: pause / floor / regime rules from closed paper trades (Lab only).
7. Replay the day's game plans against no plan.
8. First pass of a month: start the re-tune as its own `nice` process (Lab only).
9. Every day: the portfolio review with worsening-verdict alerts. Fridays: journal mirrors.
10. The post-close Telegram (`portfolio/digest.py::send_postclose`): your account's value and
    day move, the movers with their headline, verdict changes, you vs the AI account today, tomorrow's
    events. Skipped when the pass runs as the 09:20 catch-up.

Before the open, the autorun tick sends the 08:30 / 09:05 login reminder and, from 08:45, the
pre-market Telegram (`digest.py::send_premarket`, once a day): value and yesterday's move,
news on your holdings since the close, ideas for your account, the autopilot's mode.

After the pass, the **data-quality check** (`backend/system/data_quality.py`, `job:last:data_quality`,
"Data quality found" on the panel below). Failures (the job is marked failed, never the pass):
covered symbols whose newest daily bar is behind the last trading day's session once its bars are due
at 15:45 (a delisted name, or every stock a day late as on 2026-10-15), plus the live checks below.
Informational only: universe symbols with no NSE instrument, and news feeds with no new item for 3
days. The **live checks** (`data_quality.py::live`, "Data alerts now" on the panel, and a Do today
item for the admin on weekdays, `::alerts`): an ingest loop whose heartbeat is older than twice its
interval (at least 2 min) or gone, the quotes loop failing (no cached quote for the first Nifty 200
names), `scheduler:last_pass` behind the last trading day whose pass should be done (by 18:00), and the
Picks study not written for that day. `core/market_calendar.py` holds the NSE holiday set (2026 official, 2027 provisional): weekends and holidays are gaps, not misses.

A worker that wakes late after the pass already ran skips it. If no pass finished for the
previous trading day (a deploy restarted the backend during it), the long-term engine's 9:20 AM
morning pass runs the whole pass then (`backend/engine/autorun.py::_longterm_pass`), recorded
under the missed day so that day's own 4:00 PM pass still runs.

## The strategy builder — Fridays

Spawned from Friday's 4:00 PM pass while the admin Lab switch is on (`backend/builder/draft.py::start_if_due`, once per ISO week), as its own
`nice` process (`python -m backend.builder`) so minutes of backtesting never stall the API. One run at a
time (Redis lock `builder:lock`, `draft.py::LOCK`). It needs the admin's Upstox session for a year of
5-minute history; without a source the run drafts nothing and waits for next week. Swing drafts test on the
stored daily bars instead (no session needed). The result is `job:last:strategy_builder`
("Strategy builder" on the Jobs panel below), which also has **Run now** (admin `POST /system/builder/run`;
"The builder is already running." if the lock is held). What it decides: Trading & Money → Strategy builder.

## Background loops (the `jobs` process)

Started by `backend/jobs.py::start_loops` in the `jobs` container, and also in every API worker
while `RUN_BACKGROUND_JOBS` is true (default). Redis locks keep two copies safe. The price pump
stays in the API because it needs the socket hub.

| Loop | Every | Does | Code |
|---|---|---|---|
| Guardrail monitor | 60 s, 9:15 AM–3:35 PM IST | checks each user's limits against their own broker (never the AI account's) | `backend/guardrails/monitor.py` |
| Auto run | 60 s | keeps auto paper runs alive, builds game plans, long-term passes, exits | `backend/engine/autorun.py` |
| Telegram | long poll | answers linked chats, one poller per bot | `backend/guardrails/telegram_bot.py` |
| Price pump (API only) | 15 s | publishes marks and P&L to sockets | `backend/ws/pump.py` |
| Worker heartbeat | 30 s (90 s TTL) | `worker:alive:<boot>` | `backend/runs.py::keep_alive` |

Each loop tick writes `job:last:<name>` through `backend/system/jobs.py::mark`, which never
raises.

## Ingest worker loops

`backend/datalayer/worker.py`, one leader (`ingest:leader`, 30 s TTL renewed every 10 s);
each loop writes `ingest:heartbeat:<name>` after a pass that did not raise, and `/health`
reports their ages.

`quotes` 15 s · `macro` 60 s · `news_poll` 60 s · `news_process` 5 min · `calendar` 6 h ·
`flows` 30 min · `regime` 60 s · `brief` 60 s (writes hourly in session if the regime moved, sooner on material news) ·
`news_react` 60 s · `news_scan` 120 s · `news_exits` 60 s · `news_outcomes` 5 min ·
`bars` 15 min (works after 3:45 PM IST) · `fundamentals` 30 min · `plan_revise` 60 s · `corp_events` 6 h (`backend/mine/events.py`).

<!-- live:jobs -->

## Deploys

- **Push-to-deploy (default):** a push to `main` runs CI; on success the shared workflow
  (`kushgarg132/ci-workflows`, called from `.github/workflows/deploy-backend.yml`) runs on
  the VM's self-hosted runner, pulls `/home/ubuntu/deploys/NeoTrade`, and runs
  `docker compose up -d --build backend` (which also rebuilds `ingest`), with `GIT_SHA` set.
  Vercel builds the frontend from the same push.
- **Direct:** end the HEAD commit subject with `[skip ci]`, push, then in the deploy clone:
  `git pull --ff-only && GIT_SHA=$(git rev-parse HEAD) docker compose build backend && docker compose up -d backend`.
  Vercel still builds on the push (it ignores `[skip ci]`).
- The deploy clone is separate from the working repo at `/home/ubuntu/projects/NeoTrade`.
- Backlog seed (once): `docker exec neotrade-backend python -m backend.system.seed_backlog`.

## Auth and sessions

| Piece | Where |
|---|---|
| Google ID-token sign-in (no redirect flow, no client secret) | `backend/auth/google.py` |
| Users, unique on `google_sub`; role `user` / `admin` | `backend/auth/store.py`, `backend/auth/models.py` |
| Session JWT, 30 minutes | `backend/auth/jwt.py` |
| Refresh token: opaque, SHA-256 hashed, rotated, replay-detecting, httpOnly cookie on `/api/v1/auth` | `backend/auth/refresh_store.py`, `backend/routers/auth.py` |
| Every router behind `get_current_user`; admin routes behind `require_admin` | `backend/auth/dependency.py`, `backend/server.py` |
| WebSocket auth as `?token=` (browsers can't set WS headers) | `backend/ws/routes.py` |
| Per-user rate limits and input bounds on write routes | the routers |

## Secrets (locations only)

- Backend env: `/home/ubuntu/deploys/NeoTrade/.env` (Mongo, Redis, OmniRoute key, Google
  client id, JWT secret, Fernet key for broker credentials, server Telegram bot token).
- Broker credentials and users' own Telegram bot tokens: Fernet-encrypted in Mongo
  (`broker_credentials`, `alert_channels`), never returned by the API.
- OmniRoute's own secrets: `/home/ubuntu/secrets/omniroute-secrets/.env`.
- Refresh tokens are stored hashed only.

## Logs

- `docker logs neotrade-backend` / `neotrade-ingest`.
- `backend/log_redaction.py::RedactTokens` strips JWTs and `?token=` from `uvicorn.access`
  (HTTP) and `uvicorn.error` (WebSocket handshakes).
- Nginx logs without tokens (`notoken` format); older lines from before that may still hold
  tokens until the log rotates.

## Health

`GET /health` on the API: `{api: "ok", ingest: {<loop>: age in seconds}, jobs: seconds since the jobs process beat or null}` (`ingest` is empty when the worker is down, null if Redis could not be read); it does not probe Mongo or Redis itself. This page's live panels
come from the admin-only `GET /api/v1/system/status` (`backend/system/status.py`, cached 30 s).
