---
page: frontend
covers: [frontend/src/**, frontend/package.json, frontend/vite.config.*, frontend/index.html]
verified_at: 2c26d99
---
# Frontend (React 19 + Vite SPA)

The whole UI: a plain-JSX (no TypeScript) React 19 / React Router 7 / Tailwind v4 single-page app styled as a broker's "contract note". It talks to the FastAPI backend over axios (`/api/v1`, bearer token + httpOnly refresh cookie) and one shared WebSocket (`/api/v1/ws`). It deploys to Vercel (git integration, root dir `frontend`); `frontend/vercel.json` rewrites `/api/*` to the backend so the refresh cookie is first-party. There is no component library, no router data layer and no global store: each page owns its fetches with `useState` + `useEffect`, and live updates arrive through `useTopic` / `useRefetchOn`.

## Files

| path | role | key symbols |
|---|---|---|
| `frontend/package.json` | deps and scripts (`dev`, `build`, `lint`, `preview`); no `test` script | scripts `build`=`vite build`, `lint`=`eslint .` |
| `frontend/vite.config.js` | react plugin; bakes `VERCEL_GIT_COMMIT_SHA` into `import.meta.env.VITE_GIT_SHA`; `manualChunks` puts react/router/clsx/tailwind-merge in a `vendor` chunk | `define`, `manualChunks` |
| `frontend/index.html` | PWA meta, manifest link, theme-color per scheme; loads `/src/main.jsx` | `#root` |
| `frontend/vercel.json` (outside globs) | `/api/:path*` -> backend nip.io host; SPA fallback `/(.*)` -> `/index.html`; `no-cache` on `/sw.js` | `rewrites`, `headers` |
| `frontend/public/sw.js` (outside globs) | service worker: network-first navigations, never caches `/api/` | `VERSION`, `PRECACHE` |
| `src/main.jsx` | provider stack and SW registration (PROD only) | `GoogleOAuthProvider > BrowserRouter > ThemeProvider > AuthProvider > App` |
| `src/App.jsx` | route table, redirects, `gated()` wrapper, scroll-to-top, opens the socket when `user` is set | `App`, `Moved`, `JournalMoved`, `NotFound` |
| `src/utils/api.js` | axios instance, token + refresh interceptors, preferences cache, ALL endpoint builders | `api`, `refreshAccessToken`, `hardLogout`, `getPreferences`, `endpoints`, `AUTH_TOKEN_STORAGE_KEY` |
| `src/lib/ws.js` | the single `Stream` socket: subscribe, reconnect with backoff, one-shot `request` | `stream`, `Stream.request`, `isExpired` |
| `src/context/AuthContext.jsx` | `user` / `loading` / `login(idToken)` / `logout()` | `AuthProvider`, `useAuth` |
| `src/context/ThemeContext.jsx`, `themeContext.js`, `useTheme.js` | light/dark; toggles `.dark` on `<html>` | `ThemeProvider`, storage key `asi_sheet` |
| `src/context/pendingContext.js` | "Needs you" count shared from Layout | `PendingContext`, `usePendingCount` |
| `src/hooks/useStream.js` | socket hooks | `useTopic`, `useReconnect`, `useRefetchOn`, `useStreamStatus` |
| `src/hooks/useAccount.js` | which account a page shows (`all`/`ai`/`mine`), from prefs `broker_roles` | `useAccount` |
| `src/hooks/useTab.js` | `?tab=` state for tabbed pages | `useTab` |
| `src/hooks/usePrivacy.js` | "hide amounts" flag on `<html data-private>` | `togglePrivacy`, `usePrivacy` |
| `src/hooks/useSchedule.js`, `src/utils/schedule.js` | job times in copy (`EngineNow`, `EngineSwitches`, `PlanCard`, `TradingControlBar`, Settings guardrails hint) from `GET /system/schedule`; `utils/schedule.js::FALLBACK_SCHEDULE` shows until it loads | `useSchedule`, `clock12`, `FALLBACK_SCHEDULE` |
| `src/hooks/useSymbolNews.js` | `GET /news/symbols` per distinct symbol list | `useSymbolNews` |
| `src/components/Layout.jsx` | shell every page renders inside; loads nav counts; news toast | `Layout` |
| `src/components/layout/{sections.js,Sidebar,BottomNav,SectionTabs,Masthead}.jsx` | nav model and chrome | `SECTIONS`, `MINE_TABS`, `AI_TABS`, `RESEARCH_TABS`, `sectionActive` |
| `src/components/{RequireAuth,ErrorBoundary}.jsx`, `system/RequireAdmin.jsx` | route guards / crash boundary | `RequireAuth`, `RequireAdmin` |
| `src/components/doc/Doc.jsx` | the design-system primitives (see Design tokens) | `Sheet`, `Statement`/`Row`/`Cell`, `Money`, `Scrip`, `Field`, `Empty`, `Ruling`, `Tabs`, `Stamp`, `NetLine` |
| `src/components/common/*` | `Button`, `Badge`, `Card`, `Avatar`, `Markdown` (marked + DOMPurify), `MoneyBadge`, `NewsChip`, `AccountSwitch`, `StopAutopilot` | `Markdown` |
| `src/components/trading/OrderTicket.jsx` | real-money order dialog: propose -> confirm (second tap) | `OrderTicket` |
| `src/components/ChatWidget.jsx` | docked assistant; streams via `stream.request('chat')`; renders action cards | `ChatWidget`, `ActionCard` |
| `src/components/{mine,paper,settings,strategies,journal,portfolio,decisions,plan,dashboard,analysis,stock,suggestions,system}/*` | page sections (see Flows) | see tables below |
| `src/utils/*.js` | pure helpers; the only unit-tested code | `mine.js`, `promotion.js`, `library.js`, `practice.js`, `plan.js`, `news.js`, `ticket.js`, `errors.js`, `formatters.js`, `handbook.js`, `months.js`, `stocks.js`, `cn.js` |
| `src/handbook/*.md` | operator handbook text, imported `?raw` by `pages/Handbook.jsx` | `system-and-data`, `trading-and-money`, `ai-and-news`, `jobs-and-ops`, `journey` |
| `src/index.css` | Tailwind v4 `@theme`, colour tokens, utilities (`sheet`, `field-label`, `figure-md`, ...) | `:root`, `.dark`, `.private` |

## Data

The frontend owns no database. Everything below is browser state.

| store | key | writer / reader | notes |
|---|---|---|---|
| localStorage | `neotrade_token` | `AuthContext.login` and `refreshAccessToken` write; request interceptor and `ws.js` read; `hardLogout`/`logout` remove | short-lived access JWT (`utils/api.js::TOKEN_STORAGE_KEY`) |
| localStorage | `asi_sheet` | `ThemeProvider` | `light`/`dark`; default from `prefers-color-scheme` |
| localStorage | `neotrade_account` | `hooks/useAccount.js` | `all`/`ai`/`mine`, only honoured when both roles exist |
| localStorage | `neotrade_private` | `hooks/usePrivacy.js` | `on`/`off`; mirrored to `<html data-private>` |
| localStorage | `neotrade.recentStocks` | `utils/stocks.js::rememberStock` | max 8 symbols, guarded by try/catch |
| cookie (httpOnly, set by backend) | refresh token, path `/api/v1/auth` | sent via `withCredentials` | never readable from JS |
| in-memory | `prefsCache` | `utils/api.js::getPreferences` | 5 s TTL (`PREFS_TTL_MS`), dropped by any non-GET to `/settings/preferences` |
| in-memory | `refreshPromise` | `utils/api.js::refreshAccessToken` | at most one refresh in flight |
| Service worker caches | `shell-v1`, `assets-v1` | `public/sw.js` | bump `VERSION` to purge |

Preferences keys the UI reads or writes via `GET/PUT /settings/preferences` (`endpoints.settings.preferences`): `broker_roles`, `autopilot_enabled`, `autopilot_live`, `autopilot_news`, `live_strategies`, `account_size`, `max_exposure`, `per_trade_cap`, `max_trades_per_day`, `daily_loss_limit`, `cooldown_after_losses`, `cooldown_minutes`, `max_option_trades_per_day`, `max_option_lots`, `auto_paper_intraday`, `scan_enabled`, `auto_paper_longterm`, `universe` (read-only here), `rebalance_targets` (`{rule, max_stock_pct, max_sector_pct, overrides}`), `portfolio_max_loss_pct`, `portfolio_max_weight_pct` (`components/settings/AutopilotSheet.jsx`, `EngineSwitches.jsx`, `pages/Settings.jsx::GUARD_FIELDS`, `components/portfolio/Rebalance.jsx`).

## Flows

### 1. Boot and auth/session
1. `src/main.jsx` mounts the provider stack; `AuthProvider` runs `GET /auth/me` (`endpoints.auth.me`) on mount with no early return on a missing token (`context/AuthContext.jsx::AuthProvider`).
2. Request interceptor attaches `Authorization: Bearer <neotrade_token>` unless the URL is in `NO_REFRESH_PATHS` (`/auth/google`, `/auth/refresh`) (`utils/api.js::NO_REFRESH_PATHS`).
3. Response interceptor: a `detail` that is a list (FastAPI 422) is flattened to text first (`utils/errors.js::detailToText`). On **401 only** (`isAuthFailure`) and not already retried, it awaits the single shared `refreshAccessToken()` (POST `/auth/refresh`, cookie), stores the new token, sets `_retriedAfterRefresh`, and replays the request. If refresh rejects, `hardLogout()` removes the token and does `window.location.assign('/login?next=<path+search>')`. A 403 does not sign out (commit 62bac34).
4. `AuthProvider.login(idToken)` posts `/auth/google` `{id_token}`, stores `res.data.token`, sets `res.data.user`. `logout()` posts `/auth/logout` best-effort, clears token and user.
5. `Login.jsx` reads `?next=` (accepted only if it starts with `/` and not `//` or `/\`) or `location.state.from`, then `navigate(returnTo, {replace:true})`. It also shows a broker "login code" hint when the URL carries a broker redirect code.
6. `RequireAuth` shows "Retrieving note..." while `loading`, otherwise redirects to `/login` with `state.from` so a broker redirect (`/settings?code=...`) survives the detour.
7. `App` effect: when `user` is truthy, `stream.connect()`; cleanup `stream.disconnect()` (logged-out tab holds no socket).
8. User shape read by the UI: `user.role` (`'admin'` gates admin UI), `user.name`, `user.picture` (`context/AuthContext.jsx`, `components/system/RequireAdmin.jsx`, `components/layout/Sidebar.jsx`).

### 2. Live socket (`src/lib/ws.js`)
1. `Stream.connect()` takes `neotrade_token`; if missing or `isExpired` (own `exp` minus 30 s) it first calls `refreshAccessToken()`; on failure it stays disconnected.
2. `_open(token)` connects to `<VITE_API_URL>/api/v1/ws?token=<jwt>` (token in query because browsers cannot set WS headers). URL base is `VITE_API_URL`, else the production backend host in a PROD build or `http://localhost:8001/api/v1` in dev (`ws.js::SOCKET_URL`); unlike axios it is NOT same-origin in production.
3. Status machine (`useStreamStatus`): `idle` -> `connecting` -> `live`; drop -> `offline` + `scheduleReconnect` (1 s doubling to 30 s) -> `reconnecting`. `Masthead::FeedStatus` shows it.
4. `subscribe(topic, fn)` keeps handlers in a `Map`; first handler sends `{action:'subscribe',topics:[t]}`; `flushSubscriptions()` re-sends all non-`__` topics on every open; a reopen after having been live fires `onReconnect` handlers so pages refetch.
5. Frame shape: `{topic, event, data}`; `event:'ping'` is dropped.
6. `stream.request(action, payload, onEvent)` sends `{action, req_id, ...payload}` and listens on a one-off topic `chat:<id>` (chat), `quick_analysis:<id>` (quick_analyze) or `analysis:<id>` (analyze); it self-unsubscribes on `done`/`error`/`report`. If the socket is down it returns `{ok:false}` and callers fall back to HTTP (Dashboard) or print an error (ChatWidget).
7. Topics the UI subscribes to: `suggestions`, `news`, `trades`, `positions`, `runs`, `pnl`, `autopilot`, `portfolio`, `guardrails`, `prices:<BARE_SYMBOL>` (Watchlist). Each has a backend publisher (`backend/ws/pump.py`, `backend/engine/persistence.py`, `backend/autopilot/service.py`, `backend/portfolio/service.py`, `backend/guardrails/monitor.py`).
8. Hooks: `useTopic` (latest-handler ref, subscribes once per topic), `useReconnect`, `useRefetchOn(topics, fn, delay=400)` (debounces a burst, also fires on reconnect).

### 3. Layout shell (every page)
1. `Layout` loads `GET /mine/actions` (count -> `PendingContext`, badge on Mine) and `GET /today/attention` (`res.data.count` -> badge on Today), refreshes on `useTopic('suggestions')` and `useReconnect` (`components/Layout.jsx::loadPending/loadAttention`).
2. `useTopic('news')` pushes up to 3 toast alerts (`message.data` with `id`, `event|title`, `hits[{target,direction,impact}]`), auto-dismissed after 15 s, linking to `/research/news`.
3. Renders `Sidebar` (lg), `Masthead`, `<main>` wrapped in its own `ErrorBoundary`, `BottomNav` (phone), `ChatWidget`. `App.gated()` adds an outer `ErrorBoundary` + `Suspense` (pages are `React.lazy`) because a page crash before `<Layout>` mounts would otherwise be uncaught.

### 4. Today (`/`)
1. `pages/Today.jsx` calls `GET /today` (+ `getPreferences` for `autopilot_enabled`) on mount, every 60 s while visible, on `visibilitychange`, and via `useRefetchOn(['trades','suggestions','autopilot','portfolio','guardrails'])`.
2. Reads: `market.open`, `accounts{role:{broker,state}}` (`ACTIVE` else "log in" chip to `/settings?tab=accounts`), `live_armed{autopilot,strategies[]}`, `kill_switch.tripped` (-> `/settings?tab=safety`), `setup{done,total,steps[{id,label,link,done}]}`, `pulse{value,day_change,day_change_pct,pnl,pnl_pct,as_of,holdings_as_of}`, `mine_actions[]`, `mine_actions_total`, `needs_you[{kind,title,detail,link,expires_at}]`, `scoreboard{today,month}.{mine,ai}`, `ai_activity[{status,side,quantity,symbol,reason,at}]`, `backdrop{regime{label,drivers},brief,events[{at,country,title,forecast}]}`, `errors{pulse,scoreboard}`.
3. A section that failed renders in place (`errors.pulse`, `errors.scoreboard`); the rest still shows.

### 5. Mine (own broker account)
1. Overview `pages/MineOverview.jsx`: `GET /mine/overview` -> `headline{value,day_change,day_change_pct,pnl,pnl_pct,xirr,nifty_xirr,as_of,holdings_as_of}`, `drivers{month|all:{top,bottom}}`, `mix{count,top,top_pct,top_symbol,effective_holdings,correlated,sectors}`; `GET /mine/actions`; reloads on `useReconnect`, `useTopic('suggestions')`. Children: `ValueCurve` (`GET /mine/history?range=1M|6M|1Y|ALL` -> `points[{value,invested,nifty_value}]`), `WaitingCards` (`GET /chat/actions/pending`, confirm/cancel), `NeedsYou`, `Mix`.
2. `NeedsYou` rows: `{id,symbol,title,detail,action{type,side,quantity,price,suggestion_id}}`. `utils/mine.js::actionTarget` maps `action.type` `stock|tax|rebalance|ticket|idea` to a link, an `OrderTicket`, or an inline `SuggestionRecord` (loaded from `GET /suggestions?status=PENDING&mode=LONGTERM`, approve = `POST /suggestions/{id}/approve-live` twice: the first tap gets `confirm_token`, the second sends `{confirm_token}` (`NeedsYou::approveLive`, `SuggestionRecord` `liveToken`), decline = `POST .../reject`). Snooze/dismiss = `POST /mine/actions/{id}/snooze|dismiss` (7-day snooze).
3. Holdings `pages/MineHoldings.jsx`: `GET /portfolio` with `params {account:'mine', live:true}` every 5 s while `marketPhase() !== 'closed'` and the tab is visible, plus `useRefetchOn(['portfolio','trades'])`. Reads `holdings[{symbol,isin,kind(STOCK|MF|...),name,weight_pct,value,pnl_pct,last_price,close_price,avg_price,thesis_target,verdict}]`, `holdings_as_of`, `stale_since`, `at`. First-use empty state -> `POST /portfolio/refresh`. `?plan=1` opens `portfolio/Rebalance.jsx` (`GET /portfolio/rebalance/candidates`, `PUT` prefs `rebalance_targets`, `POST /portfolio/rebalance {new_money,candidates}` -> `trades[]`; a trade opens `OrderTicket` via `utils/ticket.js::ticketFrom`).
4. Stock `pages/MineStock.jsx`: `GET /mine/stock/{symbol}` (404 -> "missing") -> `position{avg_price,pnl_pct,held_since,sold}`, `verdict{current,reasons[],note,history[]}`, `lots[{buy_date,days_to_long,est_tax}]`, `unknown_qty`, `closes[{date,close}]`, `trades`, `thesis`, `dividends[{date,total|amount}]`, `events`, `news[{headline|title,url,published_at}]`. `ThesisEditor` -> `PUT /mine/thesis/{symbol}`.
5. Tax `pages/MineTax.jsx`: `GET /mine/tax?fy=<year>` (FY select from `utils/mine.js::taxYears`, first FY 2025) -> `has_history`, `realised{short_gain,long_gain,est_tax,exemption_used,exemption_left}`, `unrealised[]`, `turning_long[]`, `harvest`, `unknown[]`, `pre_2018`. Empty state offers `POST /journal/import/upstox-history {days:730}`.
6. Journal `pages/Journal.jsx` (`lockedAccount="mine"`): `GET /journal` with `params {account}` -> `summary{pnl,trips,wins,by_kind}`, `calendar[{day,pnl,trips}]`, `round_trips[{id,day,symbol,kind,direction,quantity,entry_price,exit_price,pnl,note,tags}]`, `brokers_connected`, `insights[]`, `mirror{costs{charges,net_pnl,trades_per_year,heavy_trader},benchmark{your_return,nifty_return,start}}`. Actions: `POST /journal/sync`, `POST /journal/import/upstox-history`, `POST /journal/import/zerodha-console {csv}`, note save `PUT /journal/round-trips/{id}/note`. Also `components/journal/LivePnl.jsx` (`GET /analytics/pnl?venue=live` -> `{mine,ai}`, topic `pnl` `data.live`; rows "Your account" / "AI account", AI row hidden without live trades) and `GET /trading/trades?venue=live` ("Orders placed from NeoTrade", refetched on `useTopic('trades')`), `GET /guardrails` (`events[]`, live via `useTopic('guardrails')`). `?tab=habits` shows patterns; `/mine/habits` and `/journal?tab=patterns|learning` redirect there.

### 6. AI account (paper until a strategy earns live)
1. Overview `pages/AiOverview.jsx`: `GET /today` (`autopilot{enabled,live,capital,deployed}`, `scoreboard.today.ai`), `getPreferences`, `GET /analytics/pnl?venue=paper` (also pushed on topic `pnl` as `message.data.paper`); children `EngineNow`, `TodayNet` (`pnl.today{net,realized,unrealized,costs,trades,wins,losses}`), `TradedToday` (`GET /trading/fills?venue=paper&since=<IST midnight>`).
2. `components/paper/EngineNow.jsx`: `GET /trading/runs`, `/trading/kill-switch`, `/trading/trades?status=OPEN&venue=paper&mode=LONGTERM`; Start = `POST /trading/start {mode:'INTRADAY', universe?}`, Stop = `POST /trading/stop {run_id}`, "Long-term scan" = `POST /suggestions/scan`; `useTopic('runs')` patches `progress` in place, `useTopic('trades')` refetches. Sizing is not sent (server reads prefs).
3. Activity `pages/AiActivity.jsx`: `GET /settings/autopilot/log` -> `rows[{at,status(FILLED|SENT|REFUSED),side,quantity,symbol,source,mode,reason}]`, refetch via `useRefetchOn(['autopilot'])`; `PlanCard` reads `GET /plan/today`; `StopAutopilot` -> `PUT prefs {autopilot_enabled:false}`.
4. Book `pages/Portfolio.jsx` (route `/ai/book`): `GET /trading/positions?venue=paper`, `GET /trading/trades?status=CLOSED&venue=paper&limit=1000` (`CLOSED_LIMIT`), `GET /trading/fills?venue=paper`; `utils/practice.js::periodSummary` builds the net curve client-side in IST.
5. Strategies `pages/Strategies.jsx`: `GET /strategies/library?mode=`, `GET /settings/strategies/promotion`, `GET /strategies/built`, prefs `live_strategies`, `GET /trading/trades?venue=paper[&mode]` (only when "Every paper trade" is opened); `Scorecard` -> `GET /analytics/scorecard?venue=paper[&mode]` (`days[]`, `totals{...}`, `nifty_return_pct`, per-strategy rows `strategy,trades,win_rate,net,profit_factor,max_drawdown`); `MyStrategies`/`NewStrategySheet` -> `GET /strategies/vocabulary`, `POST /strategies/describe`, `POST /strategies/built`, `POST /strategies/built/{slug}/retire|retest` (polls every 10 s while a test runs); `LearningSheet` -> `GET /journal/learning`. `?book=intraday|longterm` filters the record.
6. Settings `pages/AiLimits.jsx` = `AutopilotSheet` (autopilot Off/Paper/Live; Live requires typing `LIVE`) + `EngineSwitches` + trading limits + `EngineSettings` (per-strategy live switch writes `live_strategies`; admin-only "Run a year's backtest" -> `POST /trading/backtests/{name}`).

### 7. Research
1. `pages/Dashboard.jsx` serves `/research` (front page: `SmartSearch`, recent stocks, `Market`) and `/research/stock/:symbol`. Stock: `stream.request('quick_analyze',{symbol})` -> event `report` -> `quick{company_info,price_data,technical_analysis,flags}`; fallback `POST /agents/quick-analyze/{symbol}`. AI tab fetched lazily on first open: `stream.request('analyze')` -> `ai{sentiment{score,...},sentiment_score,analyst_summary,thesis,news_articles,events}`; fallback `POST /agents/analyze/{symbol}`. `TradingChart` 1D = `GET /agents/intraday/{symbol}` every minute. "Add to watchlist" = `POST /watchlist/add?symbol=`. Buy/Sell opens `OrderTicket`.
2. `Market.jsx`: `GET /market/indices`, `/market/global`, `/market/trending` (`percent`, `name`, `symbol`); index click -> `GET /market/index/{ticker}` + `.../analysis` (`IndexCard`, `IndexAnalysis`; NIFTY/BANKNIFTY link to `/research/options?u=`). `SmartSearch`: debounce 250 ms `GET /trading/instruments?q=` then `GET /market/quotes?symbols=`.
3. News `pages/News.jsx`: `GET /news/feed` `params {limit:50, scope?, mine?, before?}` -> `items[{id,title,url,scope,source,published_at,material,status,impacts[{type,target,direction,impact}]}]`; refetch on `useTopic('news')`.
4. Watchlist `pages/Watchlist.jsx`: `GET /watchlist/details` rows `{symbol,current_price,previous_close,day_change,day_change_percent}`; subscribes `prices:<SYM>` (`data.price`) for live ticks; remove = `DELETE /watchlist/remove/{symbol}`.
5. Options `pages/OptionChain.jsx`: `GET /options/expiries?underlying=`, `GET /options/chain?underlying=&expiry=` -> `{name,expiry,spot,atm_strike,pcr,strikes[{strike,call{oi,oi_change,ltp,iv},put{...}}]}`; `?u=NIFTY|BANKNIFTY`.
6. Picks `pages/Picks.jsx` (admin): `GET /picks` (`date,picks[],setups[],forward,caveats`) + `GET /picks/history?days=90` (`picks[]` filtered to those with `outcome`).

### 8. More: Settings, Profile, System
1. `pages/Settings.jsx` tabs (`useTab`): `accounts` (`BrokerSheet`: `GET /broker/{broker}/status`, `GET .../login-url`, `POST .../connect {request_token}` or `{client_code,password,totp}`, `POST .../disconnect`, `POST /settings/broker-credentials {api_key,...}`; role radio writes prefs `broker_roles`), `safety` (`GuardrailsSheet`: prefs + `/guardrails/telegram/{link,verify,bot}`; `PortfolioSheet`: `portfolio_max_*_pct`, admin `GET/PUT /settings/portfolio-verdicts {audience}`), `ai` (`ModelSheet` `omniroute-model|tiers|models|catalog|model/test` (writes admin-only), admin `UsageSheet` `omniroute-usage` retried 5x/4 s), `about` (admin: links to `/system`, `/system/future`, `BetaSheet` -> `GET /journal/beta-metrics`). `LEGACY_TABS` maps old `?tab=broker|guardrails|portfolio|beta`. A broker redirect lands as `?code=` (Upstox) or `?request_token=` (Kite) and is auto-submitted then stripped from the URL.
2. `pages/Profile.jsx`: `GET/PUT /profile` (`{profile{display_name,risk_appetite,horizon,goals,constraints,about_me,answer_style,memories[]},account{name,created_at}}`), `POST /profile/memories {text}` (max 50), `DELETE /profile/memories/{id}`.
3. `pages/Handbook.jsx` (admin, `/system`): five `?raw` markdown files, `utils/handbook.js::splitLive` swaps `<!-- live:deploy|jobs|news|data|ai -->` markers for `components/system/LivePanels.jsx` fed by `GET /system/status` (Jobs panel shows `data_alerts` as "Data alerts now"); panel actions: `POST /settings/llm-feature {feature,enabled}`, `POST /settings/lab {enabled}`, `POST /system/builder/run` (409 = already running).
4. `pages/Backlog.jsx` (admin, `/system/future`): `GET/POST /system/backlog`, `PATCH/DELETE /system/backlog/{id}`; optimistic writes roll back with the API message; reorder swaps `rank`.

### 9. Order ticket / chat actions (the only path to real orders from the UI)
1. `OrderTicket` (Buy/Sell, CNC, market/limit) does `POST /orders/propose {symbol,side,quantity,product,order_type,limit_price,venue:'live'}` -> card `{id,summary,...}`; Confirm = `POST /chat/actions/{id}/confirm {confirm_token}`. Response `status:'NEEDS_SECOND_TAP'` stores its `confirm_token` and arms a second tap (button disabled 600 ms) that sends it; otherwise `result` is shown. Any edit or close cancels the card (`POST /chat/actions/{id}/cancel`); unmount also cancels. No response at all is reported as "may have gone through", never as failure.
2. `ChatWidget`: `stream.request('chat',{message,history,context:{page,symbol}})` events `content`, `thinking`, `suggestions`, `action` (renders `ActionCard` using the same confirm/cancel endpoints), `done`, `error`.
3. `WaitingCards` lists `GET /chat/actions/pending` (filters expired by `expires_at`).

## Routes

Source: `src/App.jsx::App`. `gated(x)` = `RequireAuth > ErrorBoundary > Suspense > x`. Everything except `/login` is gated.

| path | page | admin-only | notes |
|---|---|---|---|
| `/login` | `Login` | no | not gated; honours `?next=` |
| `/` | `Today` | no | nav section Today |
| `/mine` | `MineOverview` | no | `MINE_TABS` Overview |
| `/mine/holdings` | `MineHoldings` | no | `?plan=1` = rebalance |
| `/mine/tax` | `MineTax` | no | |
| `/mine/stock/:symbol` | `MineStock` | no | not a tab |
| `/mine/journal` | `Journal lockedAccount="mine"` | no | `?tab=habits` |
| `/ai` | `AiOverview` | no | `AI_TABS` Overview |
| `/ai/activity` | `AiActivity` | no | |
| `/ai/book` | `Portfolio` | no | |
| `/ai/strategies` | `Strategies` | no | `?book=` |
| `/ai/settings` | `AiLimits` | no | |
| `/research` | `Dashboard` | no | |
| `/research/stock/:symbol` | `Dashboard` | no | same component, symbol from `useParams` |
| `/research/news` | `News` | no | |
| `/research/watchlist` | `Watchlist` | no | |
| `/research/picks` | `Picks` | **yes** | `RequireAdmin` redirects non-admin to `/settings`; tab hidden by `SectionTabs` |
| `/research/options` | `OptionChain` | no | not a tab; `?u=NIFTY\|BANKNIFTY` |
| `/settings` | `Settings` | no | `?tab=accounts\|safety\|ai\|about` |
| `/profile` | `Profile` | no | |
| `/import` | `Import` | no | no-broker onboarding: Console CSV (`POST /journal/import/zerodha-console`), CAS PDF + password (`POST /imports/cas`, multipart), consent note, `DELETE /imports`; linked from the Today setup checklist (`import_trades`, `import_funds`) and the empty Today/Mine/Journal states |
| `/system` | `Handbook` | **yes** | `?tab=system\|trading\|ai\|ops\|journey` |
| `/system/future` | `Backlog` | **yes** | |
| `*` | `NotFound` (inside `Layout`) | no | gated |

Redirects (`replace`, query string kept by `Moved`): `/mine/ideas` -> `/mine`; `/mine/trades` -> `/mine/journal`; `/mine/habits` -> `/mine/journal?tab=habits`; `/ai/decisions`, `/practice/decisions`, `/ai/practice/decisions`, `/decisions`, `/suggestions`, `/paper/decisions` -> `/mine`; `/ai/autopilot`, `/ai/limits`, `/practice/setup`, `/ai/practice/settings`, `/paper/settings` -> `/ai/settings`; `/practice`, `/ai/practice`, `/ai/practice/engine`, `/paper`, `/paper/engine`, `/trading` -> `/ai`; `/practice/book`, `/ai/practice/book`, `/ai/practice/holdings`, `/paper/holdings` -> `/ai/book`; `/practice/strategies`, `/practice/library` -> `/ai/strategies`; `/portfolio` -> `/mine/holdings`; `/watchlist` -> `/research/watchlist`; `/options` -> `/research/options`; `/scanner`, `/research/scanner` -> `/research`; `/journal` -> `JournalMoved` (`?tab=patterns|learning` -> `/mine/journal?tab=habits`, else `/mine/journal` + query).

### Nav sections (`components/layout/sections.js`)
- `SECTIONS` (5, all `primary`): Today `/` (exact, badge `attention`), Mine `/mine` (match `/mine`, badge `pending`), AI `/ai`, Research `/research`, More `/settings` (match `/settings`, `/profile`, `/system`). `Sidebar` (lg+) and `BottomNav` (phone) both render these; `sectionActive` keeps a section lit on all its sub-paths.
- `MINE_TABS`: Overview, Holdings, Tax, Journal. `AI_TABS`: Overview, Activity, Book, Strategies, Settings. `RESEARCH_TABS`: Search, News, Watchlist, Picks (`admin:true`, filtered in `SectionTabs`). `SystemTabs` (admin) = `HANDBOOK_TABS` + Future.

## Jobs and schedules

None run in the frontend build. Client-side timers: Today polls `/today` every 60 s while visible (`Today.jsx`); MineHoldings every 5 s while NSE is not closed (`LIVE_POLL_MS`); `TradingChart` 1D every 60 s; `MyStrategies` every 10 s while a backtest is running; `UsageSheet` retries `omniroute-usage` 5 x 4 s; socket reconnect 1 s -> 30 s. User-facing schedule strings (hard-coded copy, not read from the backend): "Next scan 4:00 PM IST" (`components/paper/EngineNow.jsx`), intraday auto-run 9:15 AM, scan 4:00 PM, long-term rebalance 9:20 AM on the first trading day of the month (`components/settings/EngineSwitches.jsx`). Deploy: Vercel builds on push; there is no frontend job in `.github/workflows/deploy-backend.yml`; CI job `frontend` runs `npm ci`, `npm run lint`, `npm run build` on Node 22 when `frontend/` changed (`.github/workflows/ci.yml`).

## Design tokens

- Real tokens live in `src/index.css`: `@theme` maps Tailwind colours to CSS variables; `:root` (paper theme) and `.dark` (carbon copy, toggled by `ThemeProvider`) define them. Variables: `--paper`, `--paper-sunk`, `--ink`, `--ink-soft`, `--ink-faint`, `--rule`, `--rule-strong`, `--stamp` (violet `#3a32a0`), `--stamp-soft`, `--ai` (teal), `--gain`, `--loss`, `--gain-wash`, `--loss-wash`, `--sheet-shadow`, `--masthead-h`, `--status-bar`. Fonts: Archivo (sans), Archivo Narrow (`--font-narrow`, labels), Courier Prime (`--font-mono`), loaded from Google Fonts at the top of the file. Radius is 0 everywhere.
- Utilities: `sheet`, `field-label`, `doc-meta`, `figure-lg`, `figure-md`, `rule-net`, `perforated`, `text-up`, `text-down`, `text-balance`; animations `stamp-land`, `restrike`; badge classes `.badge-mine|ai|paper`.
- Privacy: wrap money in an element with class `private`; `html[data-private="on"] .private :is(.figure-md,.figure-lg)` blurs it (`index.css`). Pages that show the user's own money add `private` (Today, MineHoldings, Journal, `PaperShell`).
- Prose design intent is in `DESIGN.md` (repo root); the header comment of `index.html` states the thesis (contract note, square corners, one violet stamp).
- Components must use `var(--token)` colours (`text-[var(--ink-soft)]`, `border-[var(--rule-strong)]`), `cn()` from `utils/cn.js`, and `Doc.jsx` primitives; touch targets are `min-h-11` on phones.

## Invariants

- All HTTP goes through `utils/api.js::api`; endpoint paths live in `endpoints` (commit ab83777 dropped unused entries). Never hand-build `/api/v1` URLs elsewhere. Two exceptions build paths from `endpoints.*`: `MyStrategies::act` (`${endpoints.builtStrategies}/${slug}/${action}`) and `Profile` memories delete.
- Production API base is same-origin `/api/v1` (`import.meta.env.PROD` branch) so the SameSite=None refresh cookie is first-party through Vercel's rewrite; only the WebSocket uses `VITE_API_URL`.
- Only a 401 signs the user out; a 403 must not (commit 62bac34).
- Refresh is single-flight (`refreshPromise`); a request is retried at most once (`_retriedAfterRefresh`).
- One socket per session (`stream`), opened/closed only by `App`'s effect. Pages must not open their own WebSocket.
- A stale number must never look live (PRODUCT.md, `useStreamStatus`/`FeedStatus`); after reconnect pages refetch (`useReconnect`/`useRefetchOn`). The service worker never caches `/api/`.
- Real-money order safety (backend rules mirrored in UI, from `.claude/CLAUDE.md`): the UI never places an order directly. `OrderTicket` always proposes (`venue:'live'`, the user's own `mine` account only) then confirms through `/chat/actions/{id}/confirm`, and a live order needs a second tap enforced server-side (`status:'NEEDS_SECOND_TAP'` returns a one-time `confirm_token` the second tap must send; `ChatWidget`, `WaitingCards`, `OrderTicket`, `SuggestionRecord` all carry it). The AI account is not selectable in the ticket (needs a `mine` role: `hasMine` from prefs `broker_roles`). The autopilot switch to Live requires typing `LIVE` (`AutopilotSheet`). Setting `daily_loss_limit` to 0 (which also disables the kill switch) requires an explicit confirm and never happens by a cleared field (`Settings.jsx::GuardrailsSheet`, `AutopilotSheet`).
- Admin gating in UI is cosmetic; the backend enforces (`/picks` router has `require_admin`; model/usage writes return 403). `RequireAdmin` redirects to `/settings`.
- Unknown `?tab=` falls back to the first tab (`hooks/useTab.js`).
- API `detail` is always text by the time a page reads it (interceptor), so pages may render `err.response.data.detail` directly.
- Dates: IST day boundaries (`utils/months.js::todayIst`, `utils/practice.js`), naive API timestamps are treated as UTC (`practice.js::toDate`); INR formatting via `utils/formatters.js`. Date-only fields are shown as calendar dates, not local midnight (commit 1c98111).
- LLM/Markdown text is only rendered through `common/Markdown.jsx` (marked + DOMPurify).
- localStorage access is wrapped: `utils/storage.js::safeGet/safeSet` in `ThemeContext` and the `api.js` request interceptor, try/catch elsewhere (private mode).
- The handbook (`src/handbook/*.md`) is verified against code with `file::symbol` anchors; if code and handbook disagree the code is right and the handbook is fixed in the same commit (`.claude/CLAUDE.md`).

## Endpoints

The frontend serves none. Full list of backend routes it calls (all via `utils/api.js::endpoints` unless noted), grouped by who may call them:
- Any signed-in user: `/auth/{me,google,refresh,logout}`, `/today`, `/today/attention`, `/mine/*`, `/portfolio*`, `/journal*`, `/guardrails*`, `/broker/{broker}/*`, `/orders/propose`, `/chat/actions/*`, `/trading/*`, `/suggestions*`, `/analytics/{pnl,scorecard}`, `/strategies/{library,built,vocabulary,describe}`, `/settings/{preferences,strategies,strategies/promotion,autopilot/log,broker-credentials,omniroute-*(reads),portfolio-verdicts}`, `/profile*`, `/plan/today`, `/market/*`, `/agents/{analyze,quick-analyze,intraday}/{symbol}`, `/watchlist/*`, `/options/*`, `/news/{feed,symbols}`.
- Admin (backend-enforced): `/picks`, `/picks/history`, `/system/*`, `/settings/{llm-feature,lab}`, `omniroute` model/tier writes and catalog.
- Unused by any page but present in backend: `/trading/equity`, `/broker/list`, `/journal/ai-vs-me`, `/news/market`, `/stock_info*`.

## Gotchas and known issues

- **Tests are `node:test`, not vitest.** Run `cd frontend && node --test src/utils/*.test.js` (45 tests, 10 files, no install needed). `npx vitest run` finds none. There is no `test` script. The real gate is `npm run lint && npm run build` (CI does both on Node 22); vitest/node tests do not type-check or compile JSX. `node_modules` is not committed, so run `npm ci` before lint/build.
- Only `src/utils/*.js` is covered; components, pages, hooks, `api.js`, `ws.js` have no tests.
- Vite 8 + `@vitejs/plugin-react` 6, Tailwind v4 via `@tailwindcss/postcss`, ESLint 9 flat config with `react-hooks` and `react-refresh`; `no-unused-vars` ignores names starting with a capital or `_` (`eslint.config.js`).
- The frontend ships only via Vercel (+ `VITE_API_URL`); there is no self-hosted container path (Dockerfile, nginx.conf and the compose `frontend` service were deleted 2026-10-18).
- Deploy from the repo root, not `frontend/` (Vercel Root Directory is already `frontend`; see host CLAUDE.md). `VITE_GIT_SHA` is empty on non-Vercel builds ("unknown" in the Deployed-now panel).
- `VITE_API_URL` and `VITE_GOOGLE_CLIENT_ID` must be set in the Vercel project; if `VITE_API_URL` is missing a production build's socket uses the hard-coded backend host (`ws.js::SOCKET_URL`).
- The response interceptor calls `hardLogout` only when the refresh itself returns 401; a network error or 5xx rejects the original request and keeps the session.
- `getPreferences()` is cached 5 s and shared; a component that needs fresh prefs right after writing elsewhere must write through `api.put(endpoints.settings.preferences, ...)` (which clears the cache) and use the PUT response (`AutopilotSheet`, `EngineSettings` do).
- `useAccount()` returns `account: null` until prefs load; pages must not fetch until it is non-null (`Journal.jsx` effect guard).
- Router quirks: `/research/stock/:symbol` and `/research` share one `Dashboard`; an index detail has no URL (state only). `Journal`'s `view` prop is never passed by `App` (default `'trades'`). The old `Sidebar` supports `item.divider` but no `SECTIONS` entry sets it (left in place).
- Past fixes worth knowing: 62bac34 403 no longer logs out; fddec62 failed settings saves/broker disconnect no longer silent; 57829a6 journal note save failure is shown; c2a47ed "order may have gone through" points at Mine > Journal; 1c98111 date-only fields as calendar dates; 63e529b new account can read holdings from the empty state; 1997d25 run settings drop sizing fields the server ignores; bb1aebe AI book re-reads positions on push (push carries the raw book); 023008f AI overview asks `/trading/fills` for today only; 0404502 stale-holdings rule (36 h, `utils/mine.js::STALE_MS`), FY 2025+ select.
- Job times in copy come from `GET /system/schedule` (fixed 2026-10-18); the handbook markdown still quotes times in prose.

## Tests

| file | covers |
|---|---|
| `src/utils/errors.test.js` | `detailToText` (string, 422 list, empty) |
| `src/utils/formatters.test.js` | formatters (2 cases) |
| `src/utils/handbook.test.js` | `splitLive` marker splitting / unknown panel dropped |
| `src/utils/library.test.js` | `statusOf`, `recordLine`, `builtLine`, `strategyName` |
| `src/utils/mine.test.js` | `actionTarget`, `targetProgress`, `sortHoldings`, `holdingsStale`, `taxYears` |
| `src/utils/news.test.js` | `tone`, `chipLabel`, `hasRecentNews`, `sortByNewsRisk` |
| `src/utils/plan.test.js` | `triggerLabel`, `scoreLine`, `allowSummary` |
| `src/utils/practice.test.js` | `periodSummary` (IST periods, curve, win rate) |
| `src/utils/promotion.test.js` | `promotionGaps`, `readiness`, `shortStatus` |
| `src/utils/ticket.test.js` | `ticketFrom` (sell/buy, null cases, paise rounding) |

Run: `cd frontend && node --test src/utils/*.test.js` (fast, no deps) and `cd frontend && npm ci && npm run lint && npm run build` (the real check; the build also validates every `?raw` handbook import and lazy page).
