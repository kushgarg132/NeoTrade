# Lab redesign

Date: 2026-10-27. Status: approved in chat (approach A). Frontend only: no backend change, no rebuild.

## Why

The Lab (`/settings/lab`, admin only) is a flat list of seven links plus an inline Beta card, and
every Lab page still renders the old 8-tab `SectionTabs` strip (`LAB_TABS`), including an
"Autopilot limits" tab that now lives at Settings › Admin. Settings was just rebuilt as a grouped
list with a one-line state per row and one page per setting; the Lab should read the same way.
The owner uses every Lab page, so nothing is dropped: the change is grouping, state lines,
navigation and a restyle.

## 1. Lab home (`components/settings/Lab.jsx` inside `SettingsPage title="Lab"`)

Grouped list, same `Group` + `ListRow` look as `pages/SettingsHome.jsx` (extract `Group` to
`components/settings/Group.jsx` so both use one). All reads fire in parallel on mount; each
failure leaves its state `undefined`, which its helper shows as "–". No polling.

| Group | Row | Route | State line | Source |
|---|---|---|---|---|
| Evidence | Strategies | `/settings/lab/strategies` | `N strategies · M live` | `GET /strategies/library` (`strategies[]`; live = the live switch on) |
| Evidence | Runs | `/settings/lab/runs` | `Last run <relative>` / `No runs yet` | `GET /lab/runs?limit=1` |
| Evidence | Forward | `/settings/lab/forward` | `N scored` (sum over rows) / `Nothing scored yet` | `GET /forward/scorecard` |
| Evidence | News accuracy | `/settings/lab/news` | `Built <date>`, plus ` · company scan off` when `company_scan_ok` is false; 404 = `No report yet` | `GET /news/accuracy` |
| Tools | Option chain | `/settings/lab/options` | `NIFTY · BANK NIFTY` (static) | none |
| System | Handbook | `/settings/lab/handbook` | `All checks ok` / `N failing` (blocks carrying `error`) | `GET /system/status` |
| System | Backlog | `/settings/lab/backlog` | `N open` (status not `done`/`dropped`) | `GET /system/backlog` |
| System | Beta | `/settings/lab/beta` | `N of M came back` (`returned_from_last_week` of `active_last_week`) | `GET /journal/beta-metrics` |

State helpers live in `utils/lab.js` (pure, like `utils/settings.js`), each taking the raw
response body (or `undefined`) and returning a string. Exact field names are confirmed against
the code in the plan.

## 2. Lab pages

- Every Lab page (Strategies, Runs, Forward, News accuracy, Option chain, Handbook, Backlog, new
  Beta) drops `SectionTabs`/`LAB_TABS` and renders inside `pages/SettingsPage.jsx` with
  `back="/settings/lab"` and `backLabel="Lab"` (add a `back`/`backLabel` prop to `SettingsPage`,
  default `/settings` / `Settings`). The page's existing header `right` content (badges,
  "N open", rebuild button) moves to a `right` prop on `SettingsPage`.
- `Strategies` drops `PaperShell` for that shell; its timeframe and `?book=` filters stay.
- Restyle pass on the ui kit (`Card`, `ListRow`, `Empty`, `ErrorLine`, `Skeleton`, `Badge`):
  replace leftover old-kit pieces, 44 px tap targets, no sideways scroll on a phone. Features,
  endpoints and data are unchanged.
- `Beta` becomes `/settings/lab/beta` (the existing `BetaSheet` as the page body).

## 3. Routing and cleanup

- URLs unchanged; add `beta` to `LAB_PAGES` (so it is in `ROUTES` and `ADMIN_ROUTES`).
- Delete `LAB_TABS` from `components/layout/sections.js`. Delete `PaperShell` and
  `SectionTabs` if nothing else imports them after the change.
- Update `docs/wiki/frontend.md` (Lab section) and any handbook page that names `LAB_TABS` or
  the tab strip, with `verified_at`, in the same commits.

## 4. Testing

- `utils/lab.test.js`: each helper for `undefined`, empty and normal bodies.
- Source tests: no file imports `LAB_TABS`; every Lab page renders through `SettingsPage` with
  `back="/settings/lab"`; Lab home has the three groups and eight rows.
- `npm test`, `npm run lint`, `npm run build`.
- Render check: run the Vite dev server under Playwright with the API mocked (route
  interception, an admin user, sample bodies), and screenshot the Lab home and each page at
  390 px width. No login against the prod API. The owner eyeballs the screenshots.

## Out of scope

Merging Lab pages, moving pages to other tabs, a backend `/lab/summary` endpoint, any change to
what a page computes.
