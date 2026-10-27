# Settings redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/settings` becomes one grouped list whose rows show current state and open one page each.

**Architecture:** Pure state/redirect helpers in `utils/settings.js`; the Telegram block leaves `GuardrailsSheet` for a
`TelegramLink` component; `SettingsHome.jsx` renders the grouped list; one small `SettingsPage` wrapper hosts each
existing component at `/settings/<page>`; old `?tab=` links redirect once. Frontend only.

**Tech Stack:** React 19, React Router 7, Tailwind v4 tokens, lucide-react, node:test.

**Spec:** `docs/superpowers/specs/2026-10-27-settings-redesign-design.md`

## Global Constraints

- Pages: `/settings/profile`, `/settings/brokers`, `/settings/guardrails`, `/settings/portfolio`, `/settings/notifications`, `/settings/goal`, `/settings/ai`, `/settings/autopilot` (admin), `/settings/lab` (admin). `/settings/lab/*` routes unchanged.
- Redirect map (`?tab=`): `accounts|broker -> /settings/brokers`; `limits|portfolio|safety|guardrails -> /settings/guardrails`; `alerts -> /settings/notifications`; `profile -> /settings/profile`; `ai -> /settings/ai`; `goal -> /settings/goal`; `theme -> /settings`; `lab|about|beta -> /settings/lab`; unknown -> `/settings`. Other query params kept.
- `brokerReturnTarget` returns `/settings/brokers?<params without tab>`; null when already on `/settings/brokers`.
- News alerts options: `held` "Held", `held+watched` "Held + watched", `all` "All", `off` "Off".
- Missing or pending data -> state text "–".
- Appearance: Light / Dark only (`useTheme`), inline on the list.
- No backend change. DESIGN.md tokens only; rows >= 44 px; `ChevronRight` on rows that open a page.
- Frontend checks in `frontend/`: `npm run lint && npm test && npm run build`. Implementers do not edit `docs/wiki/*` or `frontend/src/handbook/*` (Task 4 owns docs).

## Review Focus

1. A broker login return (`/settings?tab=accounts&code=X` and `/?request_token=Y`) lands on `/settings/brokers` with the param and auto-submits — Task 1 tests + Task 3 Accounts check.
2. Preferences fail to load: list still renders every row, states "–" — Task 1 helper tests with `undefined` prefs.
3. A non-admin opening `/settings/autopilot` or `/settings/lab` is refused (RequireAdmin) — Task 3 App.jsx source test.
4. Telegram link/verify still works after the move (same endpoints, same states) — Task 2 source test that `GuardrailsSheet` lost and `TelegramLink` gained `guardrails.link` / `guardrails.verify` / `guardrails.telegramBot`.
5. `daily_loss_limit` 0 with guardrails on reads "On · no daily limit", not "On · ₹0/day" — Task 1 test.

---

### Task 1: Helpers (`frontend/src/utils/settings.js`, `frontend/src/utils/routes.js`)

**Files:** Create `utils/settings.js`, `utils/settings.test.js`; Modify `utils/routes.js::brokerReturnTarget` and its test.

**Interfaces — Produces:**
- `settingsRedirect(search: string) -> string|null` — target path+query for a `?tab=` URL, null when no `tab`.
- `brokersState(prefs)`: from `broker_roles` e.g. `{kite:'mine', upstox:'ai'}` -> `"Kite: yours · Upstox: AI"`; `{}` -> `"Not connected"`; no prefs -> `"–"`.
- `guardrailsState(prefs)`: off -> `"Off"`; on + limit > 0 -> `"On · ₹5,000/day"` (`inr` from `components/ui/format`, no decimals); on + 0 -> `"On · no daily limit"`.
- `portfolioState(prefs)` -> `"Max loss 25% · weight 20%"`.
- `telegramState(t)`: `t?.linked` -> `"Linked"`, `t` -> `"Not linked"`, null -> `"–"`.
- `goalState(prefs)`: no goal -> `"Not set"`; `{kind:'beat_nifty', by}` -> `"Beat NIFTY by <Mon YYYY>"`; `{kind:'value', target, by}` -> `"<inr target> by <Mon YYYY>"`.
- `modelState(prefs)`: null model -> `"Default"`, else the model id.
- `autopilotState(prefs)`: `"Off"` | `"On · paper"` | `"On · live"`.
- `NEWS_ALERTS = [['held','Held'],['held+watched','Held + watched'],['all','All'],['off','Off']]`.

- [ ] Step 1: failing tests — every redirect key + unknown + params kept (`?tab=accounts&code=abc` -> `/settings/brokers?code=abc`); `brokerReturnTarget('/', '?request_token=y')` -> `/settings/brokers?request_token=y`, `('/settings/brokers','?code=x')` -> null; each state helper incl. `undefined` input -> `"–"` and the Review Focus 5 case.
- [ ] Step 2: `npm test` fails. Step 3: implement. Step 4: `npm test`, lint pass.
- [ ] Step 5: commit `feat(settings): state and redirect helpers [skip ci]`

### Task 2: Telegram out of the guardrails sheet (`components/settings/TelegramLink.jsx`, `components/settings/Notifications.jsx`)

**Files:** Create `components/settings/TelegramLink.jsx`, `components/settings/Notifications.jsx`, `components/settings/Notifications.test.js`; Modify `components/journal/GuardrailsSheet.jsx` (remove the Telegram block, its state and `loadTelegram`).

**Interfaces — Produces:** `TelegramLink` (no props; owns its `GET /guardrails/telegram` read, link, verify, own-bot add/remove — moved code, same endpoints and copy); `Notifications` (no props) = `TelegramLink` + a News alerts segmented control bound to `news_alerts` (`getPreferences`, `PUT endpoints.settings.preferences {news_alerts}`), options from Task 1's `NEWS_ALERTS` (Task 2 may define the same constant locally if Task 1 is not merged yet; Task 3 dedupes).

- [ ] Step 1: move the block verbatim; GuardrailsSheet keeps everything else.
- [ ] Step 2: source tests per Review Focus 4; Notifications writes `news_alerts`.
- [ ] Step 3: lint, test, build pass.
- [ ] Step 4: commit `refactor(settings): Telegram link and news alerts on their own page [skip ci]`

### Task 3: The list, the pages, routes, redirects

**Files:** Rewrite `pages/SettingsHome.jsx`; Create `pages/SettingsPage.jsx` (wrapper: `Layout` + `PageHeader back="/settings" backLabel="Settings"` + children, title prop); Modify `App.jsx` (routes per Global Constraints; `RequireAdmin` on autopilot and lab), `components/settings/Profile.jsx` (drop `ModelSheet`/`UsageSheet`), every in-app `/settings?tab=` link (`grep -rn "settings?tab=" frontend/src`); Delete `components/settings/{Alerts,Theme,Limits}.jsx`; Tests: `pages/SettingsHome.test.js` (update).

**Interfaces — Consumes:** Task 1 helpers; Task 2 `Notifications`.

- [ ] Step 1: list — groups Account / Safety / Notifications / You / Admin (admin only) with rows, states and targets from the spec table; Appearance inline Light/Dark; reads `getPreferences()`, `GET endpoints.guardrails.telegram`, `useAuth().user` once; a `?tab=` on `/settings` -> `<Navigate replace to={settingsRedirect(search)} />`.
- [ ] Step 2: pages wired; `/settings/brokers` hosts `Accounts` and its broker-return auto-submit works there.
- [ ] Step 3: update all in-app `?tab=` links; source tests: redirect wired, admin rows behind `isAdmin`, App has the 9 routes and `RequireAdmin` on two, no import of deleted files.
- [ ] Step 4: lint, test, build pass.
- [ ] Step 5: commit `feat(settings): grouped list, one page per setting, old tabs redirect [skip ci]`

### Task 4: Design pass and docs

- [ ] Step 1: invoke `impeccable:impeccable` (critique + polish + audit) on `SettingsHome.jsx`, `SettingsPage.jsx`, `Notifications.jsx`, `TelegramLink.jsx`; apply fixes within DESIGN.md tokens; say whether rendered or audited from source.
- [ ] Step 2: docs — `docs/wiki/frontend.md` (Settings flow, routes table, preference keys line incl. `news_alerts` control), handbook pages naming Settings tabs; `verified_at` on touched wiki pages; `python3 docs/wiki/stale.py` current.
- [ ] Step 3: lint, test, build pass. Step 4: commit `style(settings): polish; docs [skip ci]`

## Waves

- Wave 1: Task 1, Task 2. Wave 2: Task 3. Wave 3: Task 4. Then final review, push, Vercel deploy (frontend only; no backend rebuild needed).
