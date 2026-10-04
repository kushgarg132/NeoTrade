# UI Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Navigation becomes Today · Mine · AI · Research · More, with a new Today page and AI Overview, and existing pages reused behind section tabs.

**Architecture:** One aggregate endpoint `GET /today`. On the frontend:
- `sections.js` is rewritten to 5 sections with path-prefix matching, plus a shared `SectionTabs`.
- New routes reuse the existing pages; old routes redirect.
- `Today.jsx` and `AiOverview.jsx` are new.
- Settings tabs are regrouped.

**Tech Stack:** FastAPI + Motor (`mongomock_motor` tests); React 19, React Router 7, Tailwind v4 tokens in `frontend/src/index.css`.

**Spec:** `docs/superpowers/specs/2026-10-05-ui-restructure-design.md`

## Global Constraints

- Every old route keeps working via `<Navigate replace>`: `/portfolio`, `/journal`, `/watchlist`, `/scanner`, `/options`, `/paper`, `/paper/*`, `/suggestions`, `/trading`, `/system`.
- No page renders inside another page (each renders its own `<Layout>` once); tabs are routes.
- Colours come only from tokens. A new `--ai` token is defined in light and dark (`:root` + dark selectors in `index.css`), and DESIGN.md is updated.
- Phone first: the bottom bar holds exactly 5 items; tap targets ≥ 44px.
- Backend tests: `python3 -m pytest -q -p no:cacheprovider` (3 known failures in `test_instrument_loader_kite_refresh.py`). Frontend: `npm --prefix frontend run build`.
- Another agent shares the repo: stage only this plan's files; `git fetch && git merge --ff-only origin/main` before pushing; `[skip ci]`; deploy by hand.

## Review Focus

- A user with no roles, brokers or Telegram set: `/today` returns `setup.done == 0` and Needs-you login items for neither role (roles unset ≠ logged out). Test in Task 1.
- One `/today` part throws (e.g. the broker state call): the response is still 200 with that part `null` and `errors` naming it. Test in Task 1.
- A deep link to an old route with a query string (`/journal?tab=patterns`) lands on the matching new tab. Check in Task 2.
- Market closed: the Today strip says "Market closed" and P&L reads "as of" rather than looking live. Covered in Task 3 by `market.open` driving the label.
- A Mine page with `account=mine` but no `mine` role: it shows "Set your account in More → Accounts" instead of an empty list. Check in Task 4.

---

### Task 1: `GET /today`

**Files:** Create `backend/routers/today.py`, `backend/tests/test_today.py`; modify `backend/server.py` (include router with `get_current_user` dependency, beside `profile_router`).

**Interfaces:**
- Produces `GET /api/v1/today` with the JSON shape in the spec. Helpers inside the module:
  - `async def _accounts(prefs, user_id, credentials) -> dict`
  - `async def _needs_you(db, user_id, prefs, accounts, kill) -> list[dict]`
  - `async def _pnl_today(db, user_id, now) -> dict`
  - `async def _setup(db, user_id, prefs) -> dict`
- `get_broker_states` is injected as a dependency so tests can fake broker states.

- [ ] **Step 1: Failing tests.**
  - `test_fresh_user_has_an_empty_setup_and_no_login_nags`: no prefs → `setup.done == 0`, `setup.total == 6`, no `login` items, `accounts == {}`.
  - `test_login_needed_for_a_role_whose_broker_is_logged_out`: roles kite=ai, upstox=mine; fake states kite NEEDS_LOGIN, upstox ACTIVE → one `login` item linking `/settings?tab=accounts`; `accounts.ai.state == "NEEDS_LOGIN"`.
  - `test_needs_you_orders_proposals_by_expiry_and_includes_cards`: 2 PENDING suggestions (expiries d+3, d+1) plus 1 PROPOSED chat_action → the d+1 proposal comes before d+3; the card is included.
  - `test_pnl_today_splits_mine_and_ai`: journal round trip closed today on upstox +100; autopilot ledger closed trade today −50 → `{"mine": 100.0, "ai": -50.0}`.
  - `test_a_failing_part_degrades_not_errors`: the fake broker-state dependency raises → 200, `accounts is None`, `"accounts" in errors`.
- [ ] **Step 2:** Run `python3 -m pytest -q -p no:cacheprovider backend/tests/test_today.py` → FAIL (module missing).
- [ ] **Step 3:** Implement, reusing:
  - `engine.autorun.in_session`
  - `brokers.registry.get_broker_adapter`
  - `SuggestionStore.list(status="PENDING")`
  - `chat_actions` (status PROPOSED, `expires_at` > now)
  - `GuardrailStore.events_for` (today) and `KillSwitchStore.is_tripped`
  - `journal.roundtrips.build_round_trips` on today's trades of `brokers_for(roles, "mine")`
  - `LedgerStore(db, user_id=autopilot.service.ledger_user(uid))`
  - `ProfileStore.get`, and `GuardrailStore.telegram_channel` for the Telegram step.
- [ ] **Step 4:** Run → PASS; then the full suite.
- [ ] **Step 5: Commit** `feat(today): GET /today -- status, needs-you, P&L split, setup [skip ci]`.

### Task 2: Navigation, routes, redirects, section tabs, Settings regroup

**Files:**
- Create `frontend/src/components/layout/SectionTabs.jsx`.
- Modify `frontend/src/components/layout/sections.js` (5 sections), `Sidebar.jsx` and `BottomNav.jsx` (active by prefix), `frontend/src/App.jsx` (routes + redirects), `frontend/src/pages/Settings.jsx` (tabs: accounts, safety, ai, about; `?tab=` honoured).

**Interfaces:**
- `SECTIONS = [{label, short, path, match: string[], icon}]`. Matches:
  - Today: `["/"]` (exact)
  - Mine: `["/mine"]`
  - AI: `["/ai"]`
  - Research: `["/research"]`
  - More: `["/settings", "/profile"]`
- `SectionTabs({ tabs: [{to, label}] })`: a NavLink row in the existing `Tabs` style.
- Exported tab sets in `sections.js`:
  - `MINE_TABS`: holdings, trades, habits
  - `AI_TABS`: overview, activity, practice, limits
  - `RESEARCH_TABS`: search, scanner, options
- Routes:
  - `/` → Today (Task 3; placeholder: keep Dashboard until Task 3)
  - `/mine/holdings` → MyPortfolio; `/mine/trades` → Journal; `/mine/habits` → Journal with `tab=patterns`
  - `/ai` → AiOverview (Task 4); `/ai/activity` → AiActivity (Task 4); `/ai/limits` → page wrapping `AutopilotSheet`
  - `/ai/practice` → PaperOverview; `/ai/practice/decisions|holdings|engine|settings` → existing pages
  - `/research` → Watchlist with `SmartSearch` on top; `/research/scanner`; `/research/options`
  - Old paths → `Navigate`, carrying `location.search`.

- [ ] **Step 1:** Implement the sections, tabs, routes and redirects. Each reused page renders the matching `SectionTabs` at its top: MyPortfolio and Journal → `MINE_TABS`; Paper pages → `AI_TABS` (practice active), above their existing `PaperShell` sub-navigation; Watchlist/Scanner/OptionChain → `RESEARCH_TABS`. Internal links that pointed to old paths (`/paper/...` in `PaperShell`, `/journal` and `/settings` links in dashboard components) are updated to the new paths.
- [ ] **Step 2:** Settings tabs become Accounts (BrokerSheet), Safety (GuardrailsSheet + PortfolioSheet limits), AI (ModelSheet, AutopilotSheet link to `/ai/limits`, ProfileRow, UsageSheet for admins), About (embed `SystemArchitecturePage` content via its exported body component, or a link card to it), Beta (admin). The old tab ids (`broker`, `guardrails`, `portfolio`) map to the new ones.
- [ ] **Step 3:** `npm --prefix frontend run build` → built. Manual: every old route lands correctly, and `/journal?tab=patterns` → `/mine/habits`.
- [ ] **Step 4: Commit** `feat(ui): Today/Mine/AI/Research/More navigation with section tabs and redirects [skip ci]`.

### Task 3: Today page

**Files:** Create `frontend/src/pages/Today.jsx`, `frontend/src/components/today/StatusStrip.jsx`, `NeedsYou.jsx`, `SetupChecklist.jsx`, `PnlSplit.jsx`, `AiActivity.jsx`; modify `App.jsx` (`/` → Today, keep `Dashboard` reachable as `/research/market` for the index analysis), `utils/api.js` (`endpoints.today`).

**Interfaces:** consumes `GET /today` (Task 1); `AiActivity` reuses the `nt` stop flow via `PUT /settings/preferences {autopilot_enabled:false}`.

- [ ] **Step 1:** StatusStrip is sticky under the masthead. It shows market chip (open/closed with time), one chip per role (✓ ACTIVE / "log in ›" linking to `/settings?tab=accounts`), a loss-red "LIVE armed" chip only when armed, and a kill-switch chip when tripped.
- [ ] **Step 2:** SetupChecklist (hidden when `done == total`) shows each step with a ✓ or a link. NeedsYou shows items with expiry ("expires in 2d") and links. When empty it shows "You're clear." in display type.
- [ ] **Step 3:** PnlSplit shows two figures with `Mine` / `AI` badges, linking to `/mine/trades` and `/ai`. The label reads "today, gross" for mine, plus "as of HH:MM" when the market is closed. AiActivity shows the last 5 log rows plus a Stop button (when enabled).
- [ ] **Step 4:** The index cards from Dashboard sit below, compact (reuse `IndexCard`). The search box moves to Research.
- [ ] **Step 5:** Build → built; check at phone width that nothing overflows.
- [ ] **Step 6: Commit** `feat(today): Today page -- status strip, needs you, setup, P&L split, AI activity [skip ci]`.

### Task 4: AI Overview + Activity; Mine locked to the user's account

**Files:** Create `frontend/src/pages/AiOverview.jsx`, `frontend/src/pages/AiActivity.jsx`; modify `MyPortfolio.jsx`, `Journal.jsx` (accept `lockedAccount="mine"` from route; hide AccountSwitch; show the "Set your account" notice when no `mine` role), `App.jsx`.

**Interfaces:**
- Overview: `GET /settings/preferences`, `GET /settings/autopilot/log`, `GET /journal/ai-vs-me`, `GET /today` (`pnl_today.ai`).
- Activity: the log + open autopilot positions (`GET /today` ai part, or log rows with status FILLED and no matching SELL).

- [ ] **Step 1:** AiOverview shows autopilot state (On/Off · paper/live), deployed vs capital bar, today and month P&L, and the AI vs you table (reuse `AiVsMeSheet` by exporting it from Journal). It links to Limits.
- [ ] **Step 2:** AiActivity shows the full log list (reuse the AutopilotSheet log markup) with a Stop button.
- [ ] **Step 3:** The Mine routes pass `account=mine`. Without a `mine` role, they show a notice card linking to `/settings?tab=accounts`.
- [ ] **Step 4:** Build → built.
- [ ] **Step 5: Commit** `feat(ai): AI overview and activity; Mine pages show the user's own account [skip ci]`.

### Task 5: Visual language, docs, deploy

**Files:** `frontend/src/index.css` (`--ai` token + `.badge-ai`, `.badge-mine`, `.badge-paper`), `DESIGN.md`, `PRODUCT.md` (surfaces table rewritten to the new sections), a `frontend/src/components/common/MoneyBadge.jsx` used by PnlSplit, AiOverview and Paper overview totals; a freshness label (`updated Ns ago`) on Today P&L, reading `market.as_of`.

- [ ] **Step 1:** Add the token and badges in both themes, and use `MoneyBadge` in the three places.
- [ ] **Step 2:** Update DESIGN.md (token, badges) and PRODUCT.md (surfaces).
- [ ] **Step 3:** Run the full suite plus the build. Deploy the backend (Task 1 endpoint); Vercel builds the frontend. `/` → 200, then smoke `/api/v1/today` with no auth → 401.
- [ ] **Step 4: Commit** `feat(ui): whose-money badges and freshness; docs for the new structure [skip ci]`.
