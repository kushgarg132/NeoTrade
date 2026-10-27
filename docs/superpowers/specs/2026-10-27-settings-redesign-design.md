# Settings redesign

Date: 2026-10-27. Status: approved in chat, awaiting spec review.

## Problem

`/settings` (`pages/SettingsHome.jsx`) is a wrapped strip of seven tabs (Accounts, Alerts, Limits, Profile, Theme,
Goal, Lab) over little content. Alerts only says "Link Telegram in Limits" because the Telegram link lives inside
`components/journal/GuardrailsSheet.jsx`; Theme and Goal are one card each; the `news_alerts` preference
(`held | held+watched | all | off`) has no visible control.

## Goal

A phone-settings style screen: one grouped list whose rows show their current state and open a page each. Owner
choice (2026-10-27): grouped list, rows open pages, no tab strip.

## Non-goals

- No backend change; every setting already exists (`PUT /settings/preferences`, `/guardrails/*`, broker routes).
- No change to the Lab pages (`/settings/lab/*`) or to `/profile`.
- No behaviour change inside the moved components beyond the Telegram split.

## The list (`/settings`, `pages/SettingsHome.jsx`)

Groups and rows, top to bottom. Each row: label, current state on the right (muted), chevron when it opens a page.

| Group | Row | State | Target |
|---|---|---|---|
| Account | Profile | user's name | `/settings/profile` |
| Account | Brokers | "Kite: yours · Upstox: AI" (from `broker_roles`), "Not connected" when empty | `/settings/brokers` |
| Safety | Guardrails & daily loss | "On · ₹5,000/day" (`guardrails_enabled`, `daily_loss_limit`), "Off" | `/settings/guardrails` |
| Safety | Portfolio review | "Max loss 25% · weight 20%" (`portfolio_max_loss_pct`, `portfolio_max_weight_pct`) | `/settings/portfolio` |
| Notifications | Telegram & alerts | "Linked" / "Not linked" (`GET /guardrails/telegram`) | `/settings/notifications` |
| You | Goal | goal summary or "Not set" (`goal`) | `/settings/goal` |
| You | AI model | current model name, "Default" when null (`omniroute_model`) | `/settings/ai` |
| You | Appearance | inline Light / Dark segmented control (`useTheme`), no page | — |
| Admin (admin only) | Autopilot | "On · paper" / "On · live" / "Off" (`autopilot_enabled`, `autopilot_live`) | `/settings/autopilot` |
| Admin (admin only) | Lab | — | `/settings/lab` (today's `Lab` list) |

State reads: one `getPreferences()` (shared GET cache), one `GET /guardrails/telegram`, `useAuth().user`. Each state
is a pure function in `utils/settings.js` from those inputs; a failed or pending read shows "–" for the rows that
need it, never breaks the list.

## Pages

Each page is `Layout` + `PageHeader` (back to `/settings`, `backLabel="Settings"`) + the existing component(s):

- `/settings/profile` — `settings/Profile` (avatar, name, link to `/profile`); `ModelSheet` and `UsageSheet` move out
  to `/settings/ai`.
- `/settings/brokers` — `settings/Accounts` (incl. the `?code=` / `?request_token=` broker return handling, which must
  keep working at the new path; `utils/routes.js::brokerReturnTarget` points here).
- `/settings/guardrails` — `journal/GuardrailsSheet` without its Telegram block.
- `/settings/portfolio` — `settings/PortfolioReview`.
- `/settings/notifications` — the Telegram block extracted from `GuardrailsSheet` into
  `components/settings/TelegramLink.jsx` (link, verify, own bot add/remove, same endpoints), plus a News alerts
  choice for `news_alerts` (Held / Held + watched / All / Off) saved with `PUT /settings/preferences`.
- `/settings/goal` — `settings/Goal`.
- `/settings/ai` — `ModelSheet` (+ `UsageSheet` for admins).
- `/settings/autopilot` (admin, `RequireAdmin`) — `AutopilotSheet` + `paper/EngineSettings`.
- `/settings/lab` (admin) — `settings/Lab`.

`settings/Alerts.jsx` and `settings/Theme.jsx` are deleted (Theme's control moves inline into the list).
`settings/Limits.jsx` is deleted (its parts get their own pages).

## Old links

`/settings?tab=X` redirects once (replace) by a pure map in `utils/settings.js`:
`accounts|broker -> /settings/brokers`, `limits|portfolio|safety|guardrails -> /settings/guardrails`,
`alerts -> /settings/notifications`, `profile -> /settings/profile`, `ai -> /settings/ai`, `goal -> /settings/goal`,
`theme -> /settings`, `lab|about|beta -> /settings/lab`; unknown -> `/settings`. Query params other than `tab`
(e.g. a broker's `code`) are kept on the redirect. In-app links to `/settings?tab=...` are updated to the new paths.

## Visual direction

DESIGN.md tokens; grouped list: group heading (13 px, muted, uppercase not required), rows 44 px+ min height, a
single surface per group with dividers, state text muted and tabular where numeric, chevron `lucide-react`
`ChevronRight`. An impeccable polish/audit pass on the list and the pages once wired.

## Testing

Frontend (node:test): `settingsRedirect(tab)` for every key above and an unknown; each state helper (brokers,
guardrails, portfolio, telegram, goal, model, autopilot) incl. missing data -> "–"; source checks that admin rows
are behind `isAdmin`, that `GuardrailsSheet` no longer contains the Telegram block and `TelegramLink` does, and that
App.jsx has the new routes with `RequireAdmin` on autopilot and lab. Then lint, test, build.

## Docs

`docs/wiki/frontend.md` (Settings flow, routes table, preference keys line), `frontend/src/handbook/*` where it
names Settings tabs; `verified_at` on touched wiki pages.
