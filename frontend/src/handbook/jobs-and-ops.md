# Jobs & Ops

Everything that runs on its own, how code reaches production, and how the doors are locked.

## The daily pass — 16:00 IST

`backend/scheduler.py::run_daily_jobs`, once a day on one worker (`scheduler:daily_lock`,
`scheduler:last_pass`), recorded in `job:last:daily_pass`:

1. Expire stale proposals (3 days).
2. Close expired option positions.
3. Refresh analyst verdicts.
4. Long-term scan for every scan-enabled user → proposals, theses, Telegram.
5. Journal sync from every connected broker.
6. Learning: pause / floor / regime rules from closed paper trades.
7. Replay the day's game plans against no plan.
8. First pass of a month: start the re-tune as its own `nice` process.
9. Fridays: journal mirrors and the weekly portfolio review with worsening-verdict alerts.

After the pass, the **data-quality check** (`backend/system/data_quality.py`, `job:last:data_quality`,
"Data quality found" on the panel below): covered symbols whose newest daily bar is behind the
rest (a quote that keeps failing), universe symbols with no NSE instrument, and news feeds with no
new item for 3 days. It reports; it never fails or gates the pass.

A worker that wakes late after the pass already ran skips it. If no pass finished for the
previous weekday (a deploy restarted the backend during it), the long-term engine's 09:20
morning pass runs the whole pass then (`backend/engine/autorun.py::_longterm_pass`), recorded
under the missed day so that day's own 16:00 pass still runs.

## Loops in the API (every worker)

| Loop | Every | Does | Code |
|---|---|---|---|
| Guardrail monitor | 60 s, 09:15–15:35 IST | checks each user's limits against their broker | `backend/guardrails/monitor.py` |
| Paper orders | short interval | fills paper limit orders, sweeps stuck rows, books late live fills | `backend/engine/paper_orders.py` |
| Auto run | 60 s | keeps auto paper runs alive, builds game plans, long-term passes, exits | `backend/engine/autorun.py` |
| Telegram | long poll | answers linked chats, one poller per bot | `backend/guardrails/telegram_bot.py` |
| Price pump | 15 s | publishes marks and P&L to sockets | `backend/ws/pump.py` |
| Worker heartbeat | ~10 s | `worker:alive:<boot>` | `backend/server.py::_heartbeat` |

Each loop tick writes `job:last:<name>` through `backend/system/jobs.py::mark`, which never
raises.

## Ingest worker loops

`backend/datalayer/worker.py`, one leader (`ingest:leader`, 30 s TTL renewed every 10 s);
each loop writes `ingest:heartbeat:<name>` after a pass that did not raise, and `/health`
reports their ages.

`quotes` 15 s · `macro` 60 s · `news_poll` 60 s · `news_process` 5 min · `calendar` 6 h ·
`flows` 30 min · `regime` 60 s · `brief` 60 s (writes hourly in session if the regime moved, sooner on material news) ·
`news_react` 60 s · `news_scan` 120 s · `news_exits` 60 s · `news_outcomes` 5 min ·
`bars` 15 min (works after 15:45 IST) · `fundamentals` 30 min · `plan_revise` 60 s.

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

`GET /health` on the API: Mongo, Redis and ingest heartbeat ages. This page's live panels
come from the admin-only `GET /api/v1/system/status` (`backend/system/status.py`, cached 30 s).
