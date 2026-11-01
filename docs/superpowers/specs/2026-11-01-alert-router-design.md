# Alert router: fewer, clearer, actionable Telegram alerts

Date: 2026-11-01. Status: approved design, pending implementation plan.

## Problem

NeoTrade sends about 17 kinds of Telegram message from separate call sites, each
building its own text: plain, emoji-led, HTML, or with buttons. The owner finds
all of them too frequent, hard to read and hard to act on. Nothing records what
was sent, so volume cannot be measured.

## Goals

1. Only four kinds of event interrupt the user at once: an exit to act on, money
   moved, high-impact news on a holding, and an action the system needs to run.
2. Everything else waits for the existing pre-market (08:45 IST) and post-close
   (after the 16:00 pass) digests.
3. Every instant alert uses one card layout with buttons in place of
   "go to Portfolio → X" prose.
4. The user can mute any kind.
5. Every alert is logged, so volume can be measured by kind.
6. One new alert: ideas that are pending and expire soon (`stale_ideas`).

Out of scope: chat replies from the bot (`backend/guardrails/telegram_bot.py`),
the "alerts are on for this chat" linking reply (`backend/routers/guardrails.py`),
the in-app WebSocket news feed, and any channel other than Telegram.

## Kinds and tiers

### Instant: sent at once as a card

| kind | sources today |
|---|---|
| `exit` | stop/target hit `backend/engine/autorun.py::_level_pass`; exit rule `autorun.py` (`exits_text`) |
| `money` | autopilot fills `backend/autopilot/service.py::_notify`; autopilot run summary `autorun.py` (only when something was bought); guardrail events `backend/guardrails/monitor.py`; AI game plan `backend/plan/notify.py` |
| `news_breaking` | `backend/datalayer/reactor.py::_deliver`, when the symbol is held on the user's own account and the hit's impact ≥ `breaking_news_min` |
| `action` | log-in reminder `autorun.py`; data-quality failures `backend/system/data_quality.py` |

### Batched: queued, then sent in the next digest

| kind | sources today |
|---|---|
| `ideas` | `backend/scheduler.py` (close), `autorun.py` (morning), `reactor.py` (after news) |
| `news` | every other news hit from `reactor.py::_deliver` |
| `learning` | strategy pause and weekly learning text `scheduler.py`; factor paper summary `autorun.py`; strategy builder `backend/builder/draft.py` |
| `review` | weekly mirror `scheduler.py::_weekly_mirrors` |
| `autopilot_refused` | autopilot runs that refused everything and bought nothing |
| `stale_ideas` | new: pending ideas whose `expires_at` is before the next digest |

### Scheduled messages (schedule unchanged)

The pre-market digest, the post-close digest and the weekly report
(`backend/reports/weekly.py`). The two digests drain the queue. Items queued
after the post-close digest go out with the next pre-market digest. Items
queued on a weekend wait for Monday's pre-market digest.

The game plan is `money`, not part of pre-market: it can cap or skip the day's AI
trades, carries a Stop button, and is built from 08:45, the same minute
pre-market sends.

## Router: `backend/alerts.py`

```python
async def alert(db, user_id: str, kind: str, title: str, lines: Sequence[str] = (), *,
                symbol: str | None = None, link: str | None = None,
                buttons: list[list[dict]] | None = None) -> bool
```

In order:

1. An unknown `kind` raises `ValueError`.
2. `ideas` and `stale_ideas` go to admins only (replaces `IdeaText`); for others
   return `False` and log nothing.
3. If `prefs.alert_mute[kind]` is true, log `state="muted"` and return `False`.
4. Instant kind: render the card, send through `telegram.alert` (HTML, with
   buttons when given), and log `state="sent"` or `"failed"`. Returns whether it
   was sent; existing callers that retry on `False` (`_level_pass`) keep working.
5. Batched kind: insert `state="queued"` and return `True`.

`backend/suggestions/notify.py` keeps only `is_admin`; `notify()` and
`IdeaText` are deleted. Callers that call `telegram.send` directly for alerts
(`guardrails/monitor.py`, `system/data_quality.py`, `plan/notify.py`,
`autopilot/service._notify`) move to `alert()`. Data quality, which sends to an
admin channel today, calls `alert()` once per admin user.

### Collection `alerts`

One collection is both the log and the queue:

`{user_id, kind, title, lines, symbol, link, state, created_at, digested_at}`

`state` is one of `queued | digested | sent | muted | failed`. A TTL index on
`created_at` keeps 30 days and is created at startup with the other indexes.

### Draining

`async def drain(db, user_id) -> tuple[str, list]`: claims the user's `queued`
rows (sets `state="digested"`, `digested_at=now`) and returns an HTML
"Since last update" block grouped by kind (fixed kind order, at most 5 lines a
kind plus "…and N more"), with the claimed ids. When the digest send fails, the
digest calls `requeue(db, ids)`, which sets them back to `queued`, in the same
place `send_premarket` already releases its Redis key for a retry.

`stale_ideas` is not queued by a job: `drain` computes it from `suggestions`
(`status=PENDING`, `mode=LONGTERM`, `expires_at` before the next digest) for
admins and merges it with the pre-market idea count into one line,
"N pending, M expire before close".

## Card layout

Telegram HTML, every instant kind:

```
🔴 <b>Sell · RELIANCE</b>
Stop hit at ₹2,410 (stop ₹2,415)
Bought ₹2,600 ×10 · P&L −₹1,900
```

One icon per kind (exit 🔴, money 🤖, news_breaking 📰, action ⚠️), a bold
title, at most 3 short lines, all data HTML-escaped. No closing instruction
prose: that is a button.

Text builders (`exits_text`, `levels_text`, `proposals_text`,
`reactor.alert_text`, `pause_text` and the rest) return `(title, lines)` instead
of a joined string.

## Buttons

| kind | buttons |
|---|---|
| `exit` | **Sell ×N**: creates a PROPOSED SELL in `chat_actions` through `backend/chat/actions.py`'s existing order checks, then shows the existing Confirm/Cancel card (a live order keeps its second tap). **Open**: URL to the holding. |
| `money` | existing **Stop autopilot** (`nt:autopilot:off`) where it is sent today; **Open** |
| `news_breaking` | **Open stock**; the article URL |
| `action` | **Open** to the log-in or settings page |
| digests | **Review ideas**, **Open Today** |

The Sell button adds no order code: it reuses the confirm path and its checks.
Only the user's own tap can place an order on the `mine` account, so the
invariant that no AI order reaches `mine` holds.

URL buttons use a new setting `APP_URL` (`https://neotrade-trading.vercel.app`).
When it is unset, cards have no URL buttons.

## Prefs and Settings

`backend/prefs.py` defaults gain `alert_mute: {}` and `breaking_news_min: 7`.
`backend/routers/settings.py` validates them: `alert_mute` keys must be known
kinds with boolean values; `breaking_news_min` is an integer 1–10.

`frontend/src/components/settings/Notifications.jsx` adds one toggle per kind,
in an "Instant" group and a "In the digest" group, plus a breaking-news
threshold select next to the existing `news_alerts` control.

## Error handling

- A Telegram failure on an instant alert is logged (`state="failed"`) and never
  raised into the caller; this matches `telegram.send` today.
- A failed digest send requeues its claimed rows.
- A failure writing to `alerts` must not stop an instant send: the send happens
  first and the log write is best effort.

## Testing

- `backend/tests/test_alerts.py`: unknown kind raises; mute logs and drops;
  ideas admin-only; instant send with mocked telegram logs `sent`/`failed`;
  batched kind queues; `drain` groups, caps and claims; `requeue` restores;
  `stale_ideas` line.
- `reactor` kind choice: held + impact ≥ threshold is `news_breaking`, else `news`.
- Existing tests of the changed text builders updated to the `(title, lines)` shape.
- `Notifications.test.js` covers the toggles and threshold.
- Run `cd backend && python -m pytest`, `vitest` and `npm run build`.

## Docs

The handbook (`frontend/src/handbook/ai-and-news.md` and any page citing
`notify`) and wiki pages `docs/wiki/data-ai-jobs.md` and `docs/wiki/platform.md`
are updated in the commits that change their code, with `verified_at` bumped.

## Rollout

Commits: router and collection; call-site migration; digests; Settings UI. No
data migration. After the first trading day, query `alerts` for counts by kind
and state to confirm the volume fell.
