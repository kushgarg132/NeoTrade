# Guest browsing: use the app before signing in

Date: 2026-11-01. Status: design, awaiting review.

## Goal

A new visitor opens NeoTrade and lands in the app, not on `/login`. They can read the market
(Home, Market, Stock, Index, Sector, News) without an account. Personal features ask them to
sign in where they are, and after sign-in they stay on the same page.

Success: a signed-out browser at `https://neotrade-trading.vercel.app/` sees market data on Home,
can open a stock, an index, a sector and a news item, and meets a sign-in card (not a redirect)
on Money, AI, Ideas, the watchlist, chat and Settings. A signed-in user sees no change.

## Decisions (from brainstorming)

- Guest scope: market research only. No demo data, no guest chat, no local guest watchlist.
- Locked features: inline sign-in card in the page, nav and tabs stay visible.
- Guest landing: a guest version of Home at `/`.
- No public endpoint may call an LLM. Cached AI output (market brief, stored stock note, stored
  index analysis) is public; generating new output stays signed-in only.
- Guests get no WebSocket. Pages fall back to their existing REST paths.
- `/login` stays as a page (direct links, expired sessions on gated pages).
- Admin-only routes (`RequireAdmin`) are unchanged.

## Backend

### `get_optional_user` (`backend/auth/dependency.py`)

Same as `get_current_user` but with `HTTPBearer(auto_error=False)`. No credentials returns
`None`. A token that is present but invalid or expired raises 401, so the frontend's refresh
path still works for a signed-in user whose access token lapsed. A guest sends no token and
never gets a 401 from a public route.

### Router gating (`backend/server.py`)

Three routers lose their router-level `dependencies=[Depends(get_current_user)]` and gate per
route instead: `market_data`, `news`, `agents`. Every route on them not listed as public below
gets an explicit `Depends(get_current_user)` (or `require_admin` where it has one today).

Public (optional user):

| Route | Notes |
|---|---|
| `GET /market/indices`, `/market/trending`, `/market/global`, `/market/quotes`, `/market/scan` | Shared, cached. |
| `GET /market/brief` | Reads Redis, never calls the model. |
| `GET /market/index/{t}`, `/market/index/{t}/intraday` | Shared. |
| `GET /market/index/{t}/analysis?cached=true` | Public only with `cached=true` (stored, 404 when none). Without it, a guest gets 401. |
| `GET /market/sector/{name}` | `user` is optional; holdings overlay only when signed in. |
| `GET /research/{symbol}/note` | Stored read, never calls the model. |
| `GET /news/feed` | Guest: no held/watched/snapshot filtering; personal scopes return the general feed. |
| `GET /news/item/{id}`, `/news/symbols`, `/news/symbol/{s}`, `/news/results` | Shared; any per-user extras skipped when `user is None`. |
| `GET /agents/intraday/{symbol}` | Shared candles. |
| `POST /agents/quick-analyze/{symbol}` | No LLM. Rate key `quick_analyze:{user.id}` when signed in, else `quick_analyze:ip:{X-Real-IP}` (limit 30/60 s for guests). |

Stays signed-in: `POST /agents/analyze/{symbol}`, `/news/accuracy` (admin), everything on every
other router, the WebSocket.

Each public handler that uses `user` today must be read and its user-only branch guarded with
`if user:`. The implementation plan lists them one by one.

Nginx already limits each IP to 20 r/s with burst 60 on the API (`neotrade.conf`); no Nginx change.

### Tests (`backend/tests/`)

- With no `Authorization` header: each public route returns non-401; `analyze`, `analysis`
  without `cached`, `/mine/*`, `/watchlist`, `/news/accuracy` return 401.
- A guest `news/feed` and `market/sector` response carries no user fields (holdings, held flags).
- An invalid bearer token on a public route returns 401 (refresh path intact).
- `quick-analyze` as guest uses the IP rate key.

## Frontend

### `SignInCard` (new, `components/SignInCard.jsx`)

Card with a one-line title, one-line body naming what sign-in unlocks, and the `GoogleLogin`
button. On success it calls `useAuth().login(idToken)` and does not navigate: the page
re-renders signed in. The Google button and error handling move out of `pages/Login.jsx` into
this component, and `Login.jsx` renders it (one copy of the sign-in code). Props: `title`, `body`.

### `RequireAuth`

Signed out: render the page shell (`Layout`) with a `SignInCard` instead of redirecting to
`/login`. Loading state unchanged. The broker return (`?code=` / `?request_token=`) still works:
the URL is untouched while the card shows, and the existing `brokerReturnTarget` effect in
`App.jsx` runs once `user` is set.

### Routes (`App.jsx`)

- Public (no `RequireAuth`, still `ErrorBoundary` + `Suspense`): `/`, `/market`, `/stock/:symbol`,
  `/market/index/:ticker`, `/market/sector/:name`, `/news/:id`, and the `*` not-found page.
- Gated (sign-in card): `/money*`, `/ai*`, `/ideas*`, `/reports/weekly`, `/settings*`, `/profile`.
- `ChatWidget`: guests see the launcher; opening it shows a `SignInCard` in the panel.
- Idle tab prefetch runs for guests too (chunks are public).

### Pages

- **Home** (`pages/Home.jsx`): guest branch skips `today`, `mine.overview`, paper P&L/scorecard
  and broker login. Shows indices, the day's market brief and top news, plus one `SignInCard`
  ("Track your money and connect brokers") where the portfolio blocks sit. Signed-in Home unchanged.
- **Market** (`pages/Market.jsx`): Today, Sectors, News open to guests. Today skips its
  `/today` backdrop call when signed out. The Watchlist tab shows a `SignInCard`.
- **Stock** (`pages/Stock.jsx`): guest skips `mine.stock`, `watchlist.list`, `mine.overview`
  and the trade ticket. The Watch button opens a sign-in sheet. The "Ask AI" / fresh analysis
  action shows a `SignInCard`; the stored note still shows.
- **Index**: guest uses only `analysis?cached=true`; "Explain this move" shows a `SignInCard`.

### Session end (`utils/api.js`)

`hardLogout` today always sends the browser to `/login?next=`. New behaviour: clear the token
and signal `AuthContext` to set `user = null` (a small event, e.g. `window.dispatchEvent(new
Event('neotrade:logout'))`, that `AuthProvider` listens for). The current page re-renders: a
public page becomes its guest view, a gated page shows its `SignInCard`. No full reload.
`/login?next=` handling in `Login.jsx` stays for old links.

### WebSocket (`lib/ws`)

Unchanged: it connects only when `user` is set. Pages already fall back to REST when
`stream.request` is not ok; verify each guest path does.

### Tests

- `Login.test.js` updated for the moved sign-in code.
- `routes.test` (or `routes.js` checks): the public/gated split.
- Guest render tests for Home and Stock: no personal endpoint called, `SignInCard` shown in the
  personal slots.
- `RequireAuth` signed out renders the card, not a `Navigate`.
- `hardLogout` dispatches the event instead of `location.assign`.

## Out of scope

Demo or sample data, guest AI chat, a browser-stored guest watchlist or paper book, a marketing
landing page, guest WebSocket prices.

## Deploy

The backend and frontend ship together: a frontend that skips the gate against the old backend
would show 401 errors on public pages. Order: backend first (public routes are additive for
signed-in users), then frontend.
