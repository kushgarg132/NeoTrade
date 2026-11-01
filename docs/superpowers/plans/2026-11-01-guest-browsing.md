# Guest Browsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-out visitor lands in NeoTrade and can read the market; personal features show an inline sign-in card instead of redirecting to `/login`.

**Architecture:** Backend adds `get_optional_user` and moves three routers (`market_data`, `news`, `agents`) from router-level auth to per-route auth, making only shared, non-LLM reads public. Frontend extracts the Google sign-in into `SignInCard`, turns `RequireAuth`'s redirect into that card inside `Layout`, opens the research routes to guests, and gives Home/Market/Stock/Index a guest branch that skips personal calls.

**Tech Stack:** FastAPI, pytest + TestClient; React 19, react-router, `@react-oauth/google`, `node --test` source tests, Vite build.

**Spec:** `docs/superpowers/specs/2026-11-01-guest-browsing-design.md`

## Global Constraints

- No public endpoint may call an LLM. Public: cached/stored AI output only.
- Guests get no WebSocket (`stream.connect()` only when `user` is set, unchanged).
- A present-but-invalid bearer token on a public route still returns 401 (refresh path intact).
- Every per-account read stays behind `get_current_user`; a guest response carries no user fields.
- Guest `quick-analyze` rate key `quick_analyze:ip:{ip}`, limit 30 per 60 s; signed-in key and limit unchanged (`quick_analyze:{user.id}`, 60/60).
- Client IP = `X-Real-IP` header (set by Nginx), fallback `request.client.host`.
- `/login` stays a working page; `Login.jsx` `?next=` and `state.from` handling stays.
- `RequireAdmin` routes unchanged.
- Signed-in behaviour of every page unchanged.
- Backend tests: `cd backend && python -m pytest`. Frontend: `cd frontend && npm test && npm run build` (vitest/node tests alone are not a build check).
- A code change updates its wiki page section and `verified_at` in the same commit (`docs/wiki/platform.md` for backend auth/endpoints, `docs/wiki/frontend.md` for routes/session/shared components). Handbook pages that describe auth/session (`frontend/src/handbook/*.md`, grep `login`) fixed in the same commit if they now disagree.
- Commit subjects follow repo style (`feat(auth): ...`, `test: ...`); end each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No pushes from task implementers.

## Review Focus

1. Signed-in user whose access token expired opens a public page: the public call must 401, refresh, retry, and show the signed-in view (not silently render as guest). Pinned in Task 1 (`test_invalid_token_is_401_not_guest`).
2. Refresh cookie dead while on a public page: page must drop to the guest view with no redirect and no reload loop. Pinned in Task 4.
3. Guest opens a gated page from a broker redirect (`/settings/brokers?code=...`): the code must survive sign-in in place. Pinned in Task 5 (source test that `RequireAuth` no longer `Navigate`s and keeps the URL).
4. Guest `GET /news/feed?mine=true` (old link or shared component): must return the general feed, not 401 or 500. Pinned in Task 2.
5. Guest calls `/market/index/{t}/analysis` without `cached=true` (IndexPage "explain" path): 401, model never called. Pinned in Task 2.

---

## Wave plan

- Wave 1 (parallel): Task 1, Task 3, Task 4.
- Wave 2 (parallel): Task 2 (needs 1), Task 5 (needs 3, 4).
- Wave 3: Task 6 (needs 5).
- Wave 4: Task 7 (verification, needs all).

---

### Task 1: `get_optional_user`

**Files:**
- Modify: `backend/auth/dependency.py`
- Test: `backend/tests/test_auth_dependency.py`
- Wiki: `docs/wiki/platform.md` (auth section)

**Interfaces:**
- Produces: `async def get_optional_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer), user_store: UserStore = Depends(get_user_store)) -> Optional[User]` with `_optional_bearer = HTTPBearer(auto_error=False)`. No credentials -> `None`. Credentials present -> same checks and 401s as `get_current_user` (share one private helper, do not copy the body).

- [ ] **Step 1: Write failing tests** in `test_auth_dependency.py`, using its `_make_app` pattern with a route `@app.get("/open") async def open_(user=Depends(get_optional_user)): return {"user_id": user.id if user else None}`:
  - `test_optional_no_header_is_guest`: GET `/open` -> 200, `{"user_id": None}`.
  - `test_optional_valid_token_returns_user`: valid JWT for a stored user -> 200, `user_id == user.id`.
  - `test_invalid_token_is_401_not_guest`: `Authorization: Bearer garbage` -> 401.
  - `test_optional_token_for_deleted_user_is_401`: valid JWT, user not in store -> 401.
- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_auth_dependency.py -v` -> the four new tests FAIL (ImportError).
- [ ] **Step 3: Implement** `get_optional_user` as in Interfaces.
- [ ] **Step 4: Run** same command -> all PASS.
- [ ] **Step 5: Update** `docs/wiki/platform.md` auth section (one line on optional auth) and its `verified_at`.
- [ ] **Step 6: Commit** `feat(auth): optional-user dependency for public reads`.

---

### Task 2: Public market, news and agent reads

**Files:**
- Modify: `backend/server.py:214,219,261` (drop `dependencies=[Depends(get_current_user)]` from the `news`, `agents`, `market_data` mounts)
- Modify: `backend/routers/market_data.py`, `backend/routers/news.py`, `backend/routers/agents.py`
- Modify: `backend/tests/test_routes_require_auth.py` (replace `GET /api/v1/market/indices` sample with `GET /api/v1/mine/overview`, keep `POST /api/v1/agents/analyze/RELIANCE`)
- Create: `backend/tests/test_guest_routes.py`
- Wiki: `docs/wiki/platform.md` (endpoint list: mark public routes)

**Interfaces:**
- Consumes: `get_optional_user` (Task 1).
- Produces: the public route set below; nothing new for the frontend to import.

Public route -> dependency (every other route on these three routers gets an explicit `Depends(get_current_user)`, or keeps `require_admin`):

| Router | Public (`get_optional_user` or no user param) |
|---|---|
| `market_data` | `/market/indices`, `/market/trending`, `/market/global`, `/market/quotes`, `/market/scan`, `/market/brief`, `/market/index/{ticker}`, `/market/index/{ticker}/intraday`, `/market/index/{ticker}/analysis` (see below), `/market/sector/{name}`, `/research/{symbol}/note` |
| `news` | `/news/feed`, `/news/item/{item_id}`, `/news/symbols`, `/news/symbol/{symbol}`, `/news/results` (`/news/accuracy` stays `require_admin`) |
| `agents` | `GET /intraday/{symbol}`, `POST /quick-analyze/{symbol}` (`POST /analyze/{symbol}` stays gated) |

Handler changes:
- `get_index_analysis`: add `user: Optional[User] = Depends(get_optional_user)`; when `not cached and user is None` raise `HTTPException(401, "Sign in to generate an explanation")` before any model or DB work.
- `news_feed`: `user` optional; the `if mine:` block runs only `if mine and user`.
- `get_sector`, `news_item`, `symbol_news`, `symbol_history`, `symbol_results`: `user` becomes optional; confirm each body never dereferences `user` (today they only declare it) — if one does, guard with `if user`.
- `quick_analyze_stock`: add `request: Request`; key `quick_analyze:{user.id}` limit 60 when signed in, else `quick_analyze:ip:{ip}` limit 30, window 60. `ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")`.
- A full-file audit of each of the three routers for any route not in the table: each gets `Depends(get_current_user)` explicitly (the dependant-walk test below catches misses).

- [ ] **Step 1: Write failing tests** in `test_guest_routes.py`. Helper `_needs(route) -> set` walks `route.dependant.dependencies` recursively and collects each `.call`. Iterate `app.routes` (APIRoute, path under `/api/v1`):
  - `test_public_routes_do_not_require_user`: for each path in `PUBLIC = {...}` (exact `/api/v1/...` paths from the table, with methods), `get_current_user not in _needs(route)` and `require_admin not in _needs(route)`.
  - `test_every_other_route_on_opened_routers_requires_user`: every route whose path starts with `/api/v1/market`, `/api/v1/research`, `/api/v1/news`, `/api/v1/agents` and is not in `PUBLIC` has `get_current_user` in `_needs(route)`.
  - `test_guest_uncached_index_analysis_is_401`: `TestClient(app).get("/api/v1/market/index/^NSEI/analysis")` with `_known_index_names` monkeypatched to `{"^NSEI": "NIFTY 50"}` and `explain_index_move` monkeypatched to raise `AssertionError` -> status 401.
  - `test_guest_news_feed_mine_ignores_mine`: call `news_feed(mine=True, user=None, ...)` directly with `db.db` patched to a `mongomock_motor` DB holding one SCORED item and a `paper_positions` row for another user -> returns that item; no `$or` filter applied.
  - `test_guest_quick_analyze_uses_ip_key`: monkeypatch `backend.rate_limit.allow` to record keys and `quick_analysis` to return a stub; POST with header `X-Real-IP: 1.2.3.4` and no auth -> recorded key `quick_analyze:ip:1.2.3.4`, limit 30.
- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_guest_routes.py -v` -> FAIL.
- [ ] **Step 3: Implement** the server.py mount changes and handler changes above.
- [ ] **Step 4: Update** `test_routes_require_auth.py` sample list as in Files.
- [ ] **Step 5: Run** `cd backend && python -m pytest -q` -> all PASS (whole suite: other tests may call these handlers directly with `user=`).
- [ ] **Step 6: Update** `docs/wiki/platform.md` endpoint list (public marker) and `verified_at`.
- [ ] **Step 7: Commit** `feat(api): public market, news and quote reads for guests`.

---

### Task 3: `SignInCard`

**Files:**
- Create: `frontend/src/components/SignInCard.jsx`
- Create: `frontend/src/components/SignInCard.test.js`
- Modify: `frontend/src/pages/Login.jsx` (render `SignInCard`'s button part instead of its own `GoogleLogin` block)
- Modify: `frontend/src/pages/Login.test.js` (auth-flow assertions move to the card test where they now live)
- Wiki: `docs/wiki/frontend.md` (shared components)

**Interfaces:**
- Produces: `export const GoogleButton = ({ onDone }) => JSX` — `GoogleLogin` with the existing `theme`/`shape="square"`/`width="280"`/`[color-scheme:light]` wrapper, calls `useAuth().login(credential)`, shows the `role="alert"` `--loss-soft` error on failure, calls `onDone?.()` on success. Default export `SignInCard = ({ title, body }) => JSX`: a `Card` (`components/ui/Card`) with `title`, `body`, `GoogleButton`, and the line "Free while in beta. Not investment advice." No navigation inside either.
- `Login.jsx` uses `<GoogleButton onDone={() => navigate(returnTo, { replace: true })} />`, keeps its glow card, wordmark, broker-code line and copy.

- [ ] **Step 1: Write failing tests** (`node:test`, `readFileSync` source style like `Login.test.js`):
  - `SignInCard.test.js`: `src` matches `/login\(credentialResponse\.credential\)/`, `/GoogleLogin/`, `/filled_black/`, `/role="alert"/`, `/--loss-soft/`, `/export const GoogleButton/`; does not match `/useNavigate|navigate\(/`.
  - `Login.test.js` 'auth flow is intact': now asserts `/GoogleButton/`, `/params\.get\('request_token'\)/`, `/select-all/`, `/navigate\(returnTo/`; 'features kept' asserts `/GoogleButton/` instead of `GoogleLogin`/`filled_black`.
- [ ] **Step 2: Run** `cd frontend && node --test src/components/SignInCard.test.js src/pages/Login.test.js` -> FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** same -> PASS; `npm run build` -> succeeds.
- [ ] **Step 5: Update** `docs/wiki/frontend.md` shared components, `verified_at`.
- [ ] **Step 6: Commit** `feat(auth): SignInCard, shared Google sign-in`.

---

### Task 4: Session end without redirect

**Files:**
- Modify: `frontend/src/utils/api.js` (`hardLogout`)
- Modify: `frontend/src/context/AuthContext.jsx`
- Create: `frontend/src/utils/session.test.js`
- Wiki: `docs/wiki/frontend.md` (session handling)

**Interfaces:**
- Produces: `export const LOGOUT_EVENT = 'neotrade:logout'` in `utils/api.js`. `hardLogout()` removes the token and `window.dispatchEvent(new Event(LOGOUT_EVENT))`; no `location.assign`. `AuthProvider` listens for `LOGOUT_EVENT` and sets `user` to `null` (listener removed on unmount).
- `AuthContext` comment "the user lands on /login with the token intact" updated to the guest view.

- [ ] **Step 1: Write failing tests** `session.test.js` (source style): `api.js` matches `/export const LOGOUT_EVENT = 'neotrade:logout'/` and `/dispatchEvent\(new Event\(LOGOUT_EVENT\)\)/`, does not match `/location\.assign/`; `AuthContext.jsx` matches `/addEventListener\(LOGOUT_EVENT/` and `/removeEventListener\(LOGOUT_EVENT/`.
- [ ] **Step 2: Run** `cd frontend && node --test src/utils/session.test.js` -> FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** same -> PASS; `npm test` -> PASS.
- [ ] **Step 5: Update** `docs/wiki/frontend.md` session section, `verified_at`.
- [ ] **Step 6: Commit** `feat(auth): expired session drops to guest view, no redirect`.

---

### Task 5: Shell and routing for guests

**Files:**
- Modify: `frontend/src/components/RequireAuth.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/utils/routes.js` (add `PUBLIC_ROUTES`)
- Modify: `frontend/src/components/Layout.jsx` (skip `todayAttention` when signed out)
- Modify: `frontend/src/components/layout/SideRail.jsx` (guest: "Sign in" link to `/login` instead of avatar/profile/logout)
- Modify: `frontend/src/components/ChatWidget.jsx` (guest: panel body is `SignInCard`)
- Test: `frontend/src/components/RequireAuth.test.js` (create), `frontend/src/utils/routes.test.js` (create or extend existing)
- Wiki: `docs/wiki/frontend.md` (routes, nav)

**Interfaces:**
- Consumes: `SignInCard` (Task 3), `LOGOUT_EVENT` behaviour (Task 4).
- Produces: `export const PUBLIC_ROUTES = ['/', '/market', '/stock/:symbol', '/market/index/:ticker', '/market/sector/:name', '/news/:id']` in `routes.js`. `RequireAuth({ children, title, body })`: loading unchanged; signed out returns `<Layout><SignInCard title={title ?? 'Sign in to use this'} body={body ?? 'Your accounts, money and AI live behind sign-in.'} /></Layout>`; never `Navigate`.
- `App.jsx`: a second wrapper `open(element)` = `ErrorBoundary` + `Suspense` without `RequireAuth`, used for every path in `PUBLIC_ROUTES` and `*`. Gated routes keep `gated(...)`. `<ChatWidget />` renders for everyone. Idle `TAB_PAGES` prefetch runs regardless of `user`. Socket effect unchanged.
- Gated page copy (pass `title`/`body` to `RequireAuth` via `gated(element, copy)`): `/money*` "Your money" / "Connect a broker to see holdings, P&L and your trade journal."; `/ai*` "The AI account" / "See what the AI account trades on paper."; `/ideas*` and settings/profile use the default.

- [ ] **Step 1: Write failing tests** (source style):
  - `RequireAuth.test.js`: matches `/SignInCard/`, `/<Layout>/`; does not match `/Navigate/`.
  - `routes.test.js`: `PUBLIC_ROUTES` is a subset of `ROUTES`; contains none of `ADMIN_ROUTES`; contains none of `/money`, `/ai`, `/ideas`, `/settings`, `/profile`.
  - App source test (in `routes.test.js`, reading `../App.jsx`): every `PUBLIC_ROUTES` path appears with `open(`; `/money"` appears with `gated(`; `{user && <ChatWidget />}` is gone.
- [ ] **Step 2: Run** `cd frontend && node --test src/components/RequireAuth.test.js src/utils/routes.test.js` -> FAIL.
- [ ] **Step 3: Implement** per Interfaces, plus Layout `loadAttention` returns early when `!user` (and `useReconnect`/`useTopic` stay harmless with no socket), SideRail guest block, ChatWidget guest panel (no send, no `stream.request` when `!user`).
- [ ] **Step 4: Run** `npm test && npm run build` -> PASS.
- [ ] **Step 5: Update** `docs/wiki/frontend.md` routes/nav, `verified_at`; fix handbook lines that say every page needs sign-in (`grep -rn -i "sign.in\|login" frontend/src/handbook`).
- [ ] **Step 6: Commit** `feat(app): guests browse market pages; locked pages show sign-in`.

---

### Task 6: Guest branches on Home, Market, Stock, Index

**Files:**
- Modify: `frontend/src/pages/Home.jsx`, `frontend/src/components/market/Today.jsx`, `frontend/src/pages/Market.jsx`, `frontend/src/pages/Stock.jsx`, `frontend/src/components/stock/useStockAnalysis.js*`, `frontend/src/pages/IndexPage.jsx`
- Test: `frontend/src/pages/guest.test.js` (create)
- Wiki: `docs/wiki/frontend.md` (page to endpoint map)

**Interfaces:**
- Consumes: `useAuth().user`, `SignInCard` (Task 3).
- Guest calls allowed per page (anything else is skipped when `!user`):
  - Home: `marketIndices`, `marketBrief`, `newsFeed` (`limit: 5`). Personal blocks replaced by one `SignInCard title="Track your money" body="Sign in to connect Zerodha, Upstox or Angel One and see your holdings and P&L."`. Skipped: `today`, `mine.overview`, `analytics.pnl`, `analytics.scorecard`, `summaries.day`, `broker.loginUrl`.
  - Market: Today skips `loadToday` (`/today` backdrop) when signed out; Watchlist tab renders `SignInCard title="Your watchlist"` instead of `<Watchlist />`.
  - Stock: skips `mine.stock` (treat as `missing`), `watchlist.list`, `mine.overview`; Watch button and trade ticket open/replace with `SignInCard title="Sign in to watch or trade"`; fresh AI analysis action shows `SignInCard`; stored note (`stockNote`), `quickAnalyze` (REST, socket is down), `intraday`, `newsHistory`, `marketQuotes` stay.
  - IndexPage: guest uses only the `cached: true` analysis call; the explain/regenerate path (`stream.request('index_why')` and uncached GET) shows `SignInCard`.

- [ ] **Step 1: Write failing tests** `guest.test.js` (source style, one test per page): each file reads `useAuth`; Home's guest branch contains `SignInCard` and `marketBrief`; Market contains `SignInCard` near `watchlist`; Stock guards `endpoints.mine.stock` and `endpoints.watchlist.list` behind `user` (regex: `/if \(!user\)|user &&|user \?/` present and `SignInCard` imported); IndexPage imports `SignInCard`.
- [ ] **Step 2: Run** `cd frontend && node --test src/pages/guest.test.js` -> FAIL.
- [ ] **Step 3: Implement** per Interfaces; signed-in code paths untouched.
- [ ] **Step 4: Run** `npm test && npm run build` -> PASS.
- [ ] **Step 5: Update** `docs/wiki/frontend.md` page-endpoint map (guest column or note), `verified_at`.
- [ ] **Step 6: Commit** `feat(pages): guest views of Home, Market, Stock and Index`.

---

### Task 7: End-to-end check

**Files:** none changed unless a defect is found (fix in the owning task's files, own commit).

- [ ] **Step 1:** `cd backend && python -m pytest -q` -> PASS. `cd frontend && npm test && npm run build` -> PASS. `python3 docs/wiki/stale.py` -> exit 0.
- [ ] **Step 2:** Run the backend locally (`cd /home/ubuntu/projects/NeoTrade && python -m uvicorn backend.server:app --port 8010` with the deploy `.env`) and confirm with no token: `curl -s -o /dev/null -w '%{http_code}' localhost:8010/api/v1/market/indices` -> 200; `/api/v1/mine/overview` -> 401 or 403; `/api/v1/market/index/%5ENSEI/analysis` -> 401; `/api/v1/market/index/%5ENSEI/analysis?cached=true` -> 200 or 404.
- [ ] **Step 3:** Frontend dev server against that backend (`VITE_API_URL=http://localhost:8010/api/v1 npm run dev`), Playwright with a fresh context (no storage): `/` shows indices and the "Track your money" card, no request to `/today`, `/mine/*`, `/analytics/*`, `/summaries/*`, `/watchlist`; `/stock/RELIANCE` shows chart and price; `/money` shows the sign-in card inside the nav shell; console shows no 401 responses. Screenshots in the scratchpad.
- [ ] **Step 4:** Report results; deploy follows the session's deploy-mode answer (backend first, then frontend, per spec Deploy section).
