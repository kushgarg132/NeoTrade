# NeoTrade — roadmap

One phase per working session. Each phase states its goal, why it sits where it does, the
files it touches, and **done-when** criteria you can check yourself against before claiming
it finished.

Update the Status column when a phase lands. That column is how a future session knows
where to start — nothing else in this repo tracks it.

| Phase | Goal | Blocked by | Status |
|---|---|---|---|
| 0 | Rename to NeoTrade | — | **done 2026-09-09** |
| 1 | Multi-tenancy security | — | **done 2026-09-09** |
| 2 | Broker adapter layer | 1 | **done 2026-09-09** |
| 3 | Safety rails + backtest gate | — | **done 2026-09-09** |
| 4 | Wire the three intraday strategies | 3 | **done 2026-09-10** |
| 5 | Live execution + F&O | 1, 2, 3 | **5a (equity) done 2026-09-10**, **5b (CSP plumbing) done 2026-09-11** |
| 6 | Revive the long-term agent engine | — | **done 2026-09-11** |
| 7 | Multi-worker readiness | — | **done 2026-09-14** |
| 8 | Reposition as the discipline layer (docs) | — | **done 2026-09-26** |
| 9 | Trade journal MVP | 8 | **done 2026-09-26** (live broker sync unverified, see phase notes) |
| 10 | Behaviour insights | 9 | **done 2026-09-26** |
| 11 | Guardrails (loss cap, trade count, cooldown) | 9 | **done 2026-09-26** (square-off: preview + opt-in live, never run live) |
| 12 | Free beta, 20–50 real traders | 9, 10, 11 | **in progress** — tooling done 2026-09-26, recruiting not started |
| 13 | Billing + real domain | 12 | not started |

Two orderings are not negotiable: **Phase 3 before Phase 5** (no real order may be
placeable before the kill-switch and the gate exist), and **Phase 1 before anything that
touches broker credentials**.

---

## Phase 0 — Rename to NeoTrade — **done 2026-09-09**

### Where things live now

| | |
|---|---|
| Repo | `github.com/kushgarg132/NeoTrade` |
| Working clone | `/home/ubuntu/projects/NeoTrade` |
| Deploy clone | `/home/ubuntu/deploys/NeoTrade` |
| Backend | `https://neotrade.161.118.167.148.nip.io` (port 8000, container `neotrade-backend`) |
| Frontend | `https://neotrade-trading.vercel.app` (Vercel project `neotrade`, root dir `frontend`) |
| Session keys | cookie `neotrade_refresh`, localStorage `neotrade_token` |
| Runner labels | `self-hosted, neotrade` (the old `aistock` label still exists on runner id 2) |

`ai-stock-investor.vercel.app` remains an alias on the same project and still serves the
current build — Vercel keeps the old project-name domain after a rename. It is still in the
backend's CORS allowlist. Drop both when you are sure nothing points at it.

The old `ai-stock.161.118.167.148.nip.io` subdomain is gone: Nginx site removed, cert deleted.

### Still outstanding — needs a human

**Google Cloud Console → Credentials → the OAuth client → Authorized JavaScript origins:**
add `https://neotrade-trading.vercel.app`. Until that is done, Google sign-in fails on the
new frontend URL (it still works on the `ai-stock-investor.vercel.app` alias, which was
already authorized). Nothing in the codebase can do this step.

### Notes for whoever hits similar work later

- Changing the compose project `name:` makes Compose treat the stack as new, so it will not
  stop the old containers — the first deploy failed with `Bind for :::8000 failed: port is
  already allocated` until `ai-stock-investor-backend` was removed by hand.
- The runner label was added via
  `gh api --method POST repos/.../actions/runners/2/labels -f "labels[]=neotrade"` *before*
  the workflow started asking for it, so no deploy was ever stranded without a runner.
- A repo rename does not disturb a registered self-hosted runner; it stayed online.
- `vercel deploy` must run from the repo root, not `frontend/` — the project's Root Directory
  is already `frontend`, so deploying from inside it fails with "Root Directory does not
  exist".
- A freshly-set `vercel.app` alias 302s to Vercel SSO for a minute or so before it settles
  and serves publicly. That redirect is not a protection misconfiguration; wait and re-check.
- Backend cold start blocks for ~60s seeding the instrument master before Uvicorn serves, so
  an immediate health check after deploy returns 502. Poll rather than concluding failure.

---

## Phase 1 — Multi-tenancy security — **done 2026-09-09**

A second human is now safe to add. What changed:

- **Broker credentials are per-user and encrypted** — `backend/auth/broker_credentials.py`,
  collection `broker_credentials`, Fernet-encrypted with `CREDENTIAL_ENCRYPTION_KEY`. The
  store refuses to save when that key is unset rather than writing plaintext. The API is
  write-only: reads return `{configured, api_key_masked}`, never the secret.
- **Broker sessions are per-user** — the cache key is
  `broker:{user_id}:kite:access_token`, not the old fixed `kite:access_token`.
- **`_write_env_vars` is gone**, with both endpoints that called it. Nothing writes `.env`
  or mutates the settings singleton at runtime; a test asserts the symbols no longer exist.
- **Roles exist** — `User.role`, `require_admin` in `backend/auth/dependency.py`, populated
  from `ADMIN_EMAILS` and re-derived on every login, so revoking is an env edit plus a
  re-login.
- **The LLM model moved to Mongo** (`backend/app_settings.py`) behind that admin check. It
  is genuinely deployment-wide, so it stays shared rather than becoming per-user. A
  process-level cache keeps it reaching the synchronous `get_llm()` without a restart.
- **`/trading/start` reads risk caps from `PrefsStore`** instead of the request body, which
  could previously size past the user's saved limits.

Deployment gained two env vars: `CREDENTIAL_ENCRYPTION_KEY` (Fernet) and `ADMIN_EMAILS`.
Both are wired through `docker-compose.yml`. Losing the encryption key means every stored
credential must be re-entered.

### Notes

- `cryptography` was only ever installed transitively; it is now declared in
  `backend/requirements.txt`, since the container build would otherwise be a coin flip.
- The old startup Kite instrument refresh was deleted rather than moved: credentials are
  per-user and at startup no user is in scope. It runs on broker connect instead, which is
  also when a fresh daily token exists.
- Still deliberately shared: the `instruments` master and the `sentiment:{symbol}` cache.
  Both are market-wide reference data, not personal.

---

## Phase 2 — Broker adapter layer — **done 2026-09-09**

`backend/brokers/protocol.py` defines `BrokerAdapter`; three adapters implement it.
`KiteAdapter` is pure composition of the pieces that already existed and were already
tested (`KiteSessionManager`, `KiteProvider`, `KiteInstrumentSource`, `KiteTickerFeed`) — no
behavior change. `UpstoxAdapter` and `AngelOneAdapter` are new, real REST integrations (no
SDK, plain `httpx`) against each broker's documented API, verified live against their
published docs and — for Angel One, whose docs page is JS-rendered and unfetchable — the
official `smartapi-python` SDK source directly. Each adapter file's docstring states exactly
what was checked, since (as with the original Kite integration) no live account exists to
test any of the three against for real.

`backend.brokers.registry.get_broker_adapter(broker, user_id, credentials, redis)` is the
one place that knows which brokers exist. `/broker/kite/*` became `/broker/{broker}/*`;
`/trading/start`'s intraday tick-feed selection and the instrument-master refresh on connect
both go through the registry now, so a connected Upstox or Angel One session gets the same
treatment Kite alone used to.

### Two real design frictions, handled rather than hidden

- **Instrument identity isn't shared across brokers.** Kite's `instrument_token` is a
  proprietary numeric ID; Upstox's real query key is an ISIN-based string
  (`NSE_EQ|INE...`); Angel One has its own numeric `token`. A row in the shared
  `instruments` collection, populated by whichever broker last refreshed it, cannot be
  handed to a different broker's API. `UpstoxAdapter`/`AngelOneAdapter` resolve their own
  broker-native key internally, from a cached scrip-master lookup keyed by
  `(exchange, tradingsymbol)`, rather than trusting the `Instrument.instrument_token` they
  were passed.
- **The connect flow has two genuinely different shapes.** Kite and Upstox redirect the
  user and exchange a short-lived code. Angel One has no redirect: the human submits a
  client code, account password, and a fresh TOTP directly, and only the app-level API key
  is worth storing long-term. `BrokerAdapter.connect(**fields)` plus
  `login_url() -> Optional[str]` (null means "show the credential form, not a redirect
  button") cover both without either adapter faking the other's shape.

### Where the done-when criteria stand

- A user can connect any of the three brokers from Settings' broker picker — verified.
- Adding a fourth broker means one new adapter file plus one line in `BROKERS` — verified
  by `test_broker_registry.py`.
- No module *outside the adapter package* imports a broker SDK, with one named exception:
  `backend/auth/kite_session.py` still imports `kiteconnect` directly. It was left in place
  rather than moved into `backend/brokers/`, to avoid touching its already-covered tests for
  a pure rename. It is reachable only from `backend/brokers/kite.py` now — nothing else in
  the app touches a broker SDK.
- Streaming ticks: only Kite's `ticker_feed()` returns a real feed in this pass;
  Upstox/Angel One return `None` and callers fall back to polling, the same path used when
  no broker is connected at all. Both do have documented WebSocket APIs — wiring them is
  future work, not blocked on anything.

---

## Phase 3 — Safety rails + backtest gate — **done 2026-09-09**

**Goal.** Make the two non-negotiable protections real before any real order can exist.

**Work:**

- **Daily loss kill-switch**: halts live trading for the rest of the session once
  realized + unrealized loss crosses the user's configured limit. Does not re-arm on its
  own; surfaces as a first-class UI state (see `PRODUCT.md`).
- **Per-trade and per-day capital caps**, enforced inside `size_intents`
  (`backend/engine/runner.py:50-143`) so no caller can route around them.
- **Backtest gate**: persist dated `BacktestResult`s per strategy and refuse to run a
  strategy live unless its stored result meets the criteria below. Requires computing
  `max_drawdown` and `sharpe_ratio`, which are hardcoded `0.0` today
  (`backend/engine/backtest.py:94-95`).

**Proposed gate criteria — confirm before implementing:** backtest window ≥1 year, ≥30
trades, profit factor ≥1.3, max drawdown ≤15%.

**Done when:** a strategy without a passing stored backtest cannot be started in live mode,
proven by a test; tripping the loss limit halts trading and the state is visible in the UI;
drawdown and Sharpe are real numbers.

### What landed

- `backend/risk/backtest_gate.py` — `passes_gate` (pure) + `BacktestGateStore` (collection
  `strategy_backtests`, one doc per run, `live_eligible` follows the latest only). Wired into
  `/trading/start`: `live_eligible_strategies` filters the candidate list before a run
  starts, so an unproven strategy 400s with a distinct message rather than silently running.
- `backend/risk/kill_switch.py` — `should_trip` (pure: `equity <= -daily_loss_limit`) +
  `KillSwitchStore` (collection `kill_switch_trips`, one doc per `(user_id, IST calendar
  date)`, `$setOnInsert` so a restarted run re-detecting the same breach can't move when the
  trip "started"). `run()` checks it once per bar; once tripped, `size_intents` drops new
  INTRADAY orders for the rest of that run — LONGTERM ones are untouched since they only ever
  reach a human-approved inbox. `GET /trading/kill-switch` surfaces today's state; the
  Trading page shows a destructive banner with the reason when tripped.
- `size_intents` gained `per_trade_cap` — a straight notional check ahead of the existing
  exposure check, so a single trade can't consume the whole per-day cap alone.
- `compute_max_drawdown`/`compute_sharpe_ratio` (`backend/engine/metrics.py`) replace the
  hardcoded `0.0`s in `run_backtest`.
- New per-user prefs `per_trade_cap` (₹100,000 default) and `daily_loss_limit` (₹50,000
  default) in `backend/prefs.py`, editable from Settings → Mandate the same way
  `account_size`/`max_exposure` already were.

### Note for later

`per_trade_cap`/`daily_loss_limit` are read once at `/trading/start` and baked into that
run's `size_intents` calls — changing them in Settings takes effect on the *next* run, not
a running one. Consistent with how `account_size`/`max_exposure` already worked; flagging it
here since Phase 3 is what makes it a safety-relevant behavior rather than a cosmetic one.

---

## Phase 4 — Wire the three intraday strategies — **done 2026-09-10**

**Goal.** Put `VWAPReversionStrategy`, `ORBStrategy` and `RSIMomentumScalpStrategy` into
`backend/strategies/registry.py:16-59` — the only thing keeping them out of live trading
today is their absence from that list.

Backtests from the session that wrote them: VWAP Reversion was profitable on a thin sample
(2 trades); ORB and RSI Momentum Scalp were both negative and were then tuned without
re-validation. Treat all three as unproven — Phase 3's gate is what decides, not this note.

`backend/tests/test_strategies_ported.py:357-359` hard-codes
`len(strategies) == 4` and will fail; update it deliberately rather than deleting the
assertion.

**Done when:** each of the three has a stored backtest result, the gate's verdict on each is
recorded, and only the ones that passed are live-eligible.

### What landed

`VWAPReversionStrategy`, `ORBStrategy`, `RSIMomentumScalpStrategy` are in
`backend/strategies/registry.py`'s default set (now 7 strategies total, 4 INTRADAY + 3
LONGTERM). `backend/tests/test_strategies_ported.py`'s hardcoded counts were updated
deliberately (7, and 8 with `quality_momentum`), not deleted.

Real backtests ran against yfinance 5m data for the full `ALL_SCAN_STOCKS` universe (79/83
symbols resolved) and were recorded into the real `strategy_backtests` collection via
`BacktestGateStore.record`. Also backtested `volume_surge` — the pre-existing 4th intraday
strategy, which had never been through the Phase 3 gate before it existed:

| Strategy | Trades | Window | Win rate | Profit factor | Max drawdown | Sharpe | Verdict |
|---|---|---|---|---|---|---|---|
| volume_surge | 509 | 58d | 0.48 | 0.91 | 11.89% | -1.21 | **FAIL** |
| vwap_reversion | 128 | 58d | 0.47 | 0.91 | 19.91% | -1.16 | **FAIL** |
| orb_breakout | 198 | 58d | 0.42 | 0.64 | 25.37% | -4.20 | **FAIL** |
| rsi_momentum_scalp | 84 | 58d | 0.48 | 0.72 | 25.66% | -2.38 | **FAIL** |

**All four fail the gate.** Two independent reasons, both real: yfinance's 5-minute
intraday data caps at roughly 58-60 days no matter what range is requested (Phase 3's fix to
`backend/engine/backtest.py` makes `BacktestResult.start_date/end_date` report that real
span, not a claimed one — see Phase 3's own notes), so none can ever clear the 365-day
window criterion against this data source. Separately, on the data that *does* exist, none
of the four are actually profitable (profit factor <1 for two, drawdowns 12-26%) — this
isn't just a data-availability technicality, the strategies as tuned currently lose money.

No strategy is live-eligible. This is the gate doing its job, not a bug — see this file's own
docstring in `backend/risk/backtest_gate.py`. Two real follow-ups this surfaces, neither
solved here: (1) a longer-history intraday data source is needed before any 5m strategy can
ever pass on window alone (a live broker's own historical API, once one is connected, likely
has more than yfinance's ~60 days); (2) the strategies' actual profitability needs rework
independent of the window question. No standalone backtest script is checked into this repo
— the one used here (fetch each symbol's 5m history once, run each strategy through
`run_backtest`, record into `BacktestGateStore`) was a scratch file, not committed. Whoever
re-validates these strategies next will need to write a similar one-off runner.

---

## Phase 5 — Live execution + F&O — **Phase 5a (equity live execution) done 2026-09-10**

**Goal.** Real orders, and derivatives.

**Work:**

- `BrokerExecutionClient` implementing `ExecutionClient`
  (`backend/engine/protocols.py:49-53`) over `BrokerAdapter`, alongside the simulated one.
- Order state machine: submitted → acknowledged → partially filled → filled / rejected /
  cancelled. Idempotent submission so a retry cannot double-place.
- Reconciliation: the broker's own fills and positions are the source of truth, not the
  local `Portfolio`. Reconcile on startup and on reconnect.
- Per-user, per-strategy paper/live toggle. Replace the `TRADING_LIVE_ENABLED` dead-man's
  switch (`routers/trading.py:164-168`).
- Instrument model widens to `(symbol, exchange, instrument_type, lot_size, expiry, strike,
  option_type)`; sizing becomes lot-aware and margin-aware; positions gain expiry handling.

**Done when:** a live order placed by the engine appears in the broker's own order book and
reconciles back into the ledger with matching quantity and price; a deliberately rejected
order leaves the local book unchanged; an F&O position sizes in whole lots and respects
margin.

### What landed (Phase 5a only)

- **Live equity execution** for Kite, Upstox, and Angel One brokers, placing real MARKET
  orders via `BrokerExecutionClient` (Tasks 1-12). Gated by per-strategy live/paper toggle
  (defaulting to all-paper), broker connection status, and backtest gate. No live broker
  account exists to verify any of it against a real broker.
- **Per-user, per-strategy paper/live toggle** in `PrefsStore` (each user, each strategy can
  choose PAPER or LIVE); `TRADING_LIVE_ENABLED` configuration variable removed entirely.
  Default state: all strategies in PAPER mode on fresh user.
- **Reconciliation on run start** (`backend/routers/trading.py`, inline in `start_trading`) —
  broker's open positions are read and merged into the local ledger so the engine's subsequent
  orders are against current broker state, not just its own knowledge. This runs once, at
  `/trading/start`, not on every status-poll tick as the design doc originally envisioned — a
  deliberate scope-down from Task 11, so a manual trade or missed fill during a long-running
  session won't self-correct until the run is restarted.
- **No F&O (derivatives) in this pass.** The instrument model remained `(symbol, exchange)`
  and sizing stayed notional. See Phase 5b below — F&O plumbing plus one real strategy landed
  2026-09-11.

### What landed (Phase 5b — F&O plumbing + cash-secured put, 2026-09-11)

Design: `docs/superpowers/specs/2026-09-11-phase-5b-fno-cash-secured-put-design.md`. Plan:
`docs/superpowers/plans/2026-09-11-phase-5b-fno-cash-secured-put.md`.

- **`Instrument` widened** with `expiry`/`strike` (both `Optional`, `None` for equities).
  `instrument_type` (already generic) carries CE/PE/FUT for F&O rows — no separate
  `option_type` field, it would have duplicated existing data.
- **`backend/options/`** — new package: `resolver.py` (deterministic strike/expiry selection
  off a small curated F&O-eligible symbol table, no live option-chain lookup exists to query),
  `pricing.py` (Black-Scholes premium off realized volatility as an IV proxy, flat-%
  margin approximation), `sizing.py` (lot-based collateral-budget sizing, a deliberately
  separate function from equity `size_intents`' stop-distance risk formula — the two sizing
  models don't share meaning).
- **`CashSecuredPutStrategy`** — new LONGTERM strategy (8th in the default set), reuses
  `MeanReversionStrategy`'s oversold trigger, emits an `option_flavor="CSP"` Intent that
  `size_intents` dispatches to the options sizer instead of the equity path.
  `is_fo_eligible` gates it to `resolver.STRIKE_INTERVALS`' curated symbols only.
- **Rides the existing suggestion/approval pipeline unmodified in structure.** Investigated
  during design: LONGTERM suggestions never reach a real broker even on approval
  (`suggestions/service.py::execute_suggestion` always synthesizes a paper fill) — true for
  every LONGTERM strategy, not just this one — so CSP is PAPER-only by the same construction
  the other four LONGTERM strategies already are, with no backtest-gate interaction (that gate
  only filters the INTRADAY live/paper toggle, never LONGTERM).
- **Expiry close-out**: a fourth daily scheduler job closes any open option position past
  expiry (worthless if OTM, simple intrinsic-value approximation if ITM).
- **Only Kite's instrument source maps `expiry`/`strike`** (verified against the installed
  pykiteconnect package's own `_parse_instruments` source). Upstox/AngelOne's `instruments()`
  never mapped those columns either — real per-broker scrip-format verification needed before
  extending them, not done here. The CSP strategy is exercisable end to end with a connected
  Kite session; Upstox/AngelOne accounts won't populate NFO contracts for it yet.
- **No live broker margin-API integration.** `estimate_margin` is the flat-percentage
  approximation only — the spec's "try the broker's own margin endpoint first" needed more
  per-adapter verification than this pass did; deferred, not silently dropped.
- **No covered call.** CSP alone. Covered call is a natural follow-on once these primitives
  exist, but needs its own trigger (against an existing long position).

### Phase 5b and beyond — still open

- Upstox/AngelOne NFO `expiry`/`strike` instrument mapping (needs real per-broker scrip-format
  verification, same posture as every other broker-specific claim in this codebase).
- Live broker margin-API integration (`estimate_margin`'s upgrade path — see
  `backend/options/pricing.py`'s `ponytail:` comment).
- Covered call strategy.
- ~~Real option-chain data source~~ -- **2026-09-27:** live NIFTY/BANK NIFTY chains from the
  user's Upstox session (`UpstoxAdapter.option_chain`/`option_expiries`, `/options/*`, the
  Option chain page). Verified against the official SDK's generated models; upstox.com was
  not reachable to check the live docs, and no account exists to call it for real. Kite has
  no chain endpoint, so it is Upstox-only.
- **2026-09-27, real contracts and live premiums for the cash-secured put.** The sizer now
  picks from the listed contracts in the broker's own NFO dump
  (`InstrumentMaster.option_contracts`, synced when Kite connects): the soonest expiry at
  least 5 days out, at the listed strike nearest 5% OTM. `resolver.py`'s computed
  last-Thursday expiry, strike-interval table and symbol formatter are gone (only the
  eligible-underlying list remains, as `FO_UNDERLYINGS`). Premiums come from
  `backend/options/premiums.py` -- a Kite quote of the contract, else the Upstox chain --
  with the Black-Scholes estimate kept only as a flagged fallback (`premium_is_live`).
  Approving an option proposal fills at the live premium; it previously priced the NFO
  symbol as an NSE equity and always failed with "Unknown instrument", so no option
  proposal had ever filled. Upstox's own NFO instrument mapping is still open: contracts
  come from Kite's dump.
- **2026-09-27, options in the journal and guardrails.** Every round trip carries `kind`
  (STOCK/CALL/PUT/FUTURE, from the broker's symbol and exchange -- including the spaced
  "NIFTY 25100 CE 30 SEP 25" form) and `underlying`. The journal summary splits P&L by
  stocks/options/futures; findings add options bought vs sold and options vs stocks. Three
  opt-in guardrails: options trades per day, lots per options trade (lot sizes from the NFO
  dump, so Kite must have synced), and a warning on an option sold with no bought option on
  the same underlying open (strike/expiry/type not matched -- see `guardrails/rules.py`).
  Alerts only: nothing here can stop an order placed in the broker's own app. Not done:
  expiry-day findings (needs a reliable expiry per traded contract).
- **2026-09-27, intraday options on paper.** `orb_options`
  (`backend/strategies/intraday/orb_options.py`) takes `orb_breakout`'s trigger on the
  `FO_UNDERLYINGS` large-caps and buys the at-the-money call on a breakout, the put on a
  breakdown (`option_flavor` LONG_CALL / LONG_PUT). `size_option_intent` sizes it by premium
  outlay (2% of account at full conviction, max 2 lots, soonest expiry at least a day out)
  and only with a live premium -- no model-priced intraday fills. The runner fills it at the
  premium it just read, keeps one such trade per underlying per day, and sells it when the
  underlying reaches the strategy's stop or target or at 15:15 (`_option_exit_orders`),
  counting its marked premium in the kill-switch's P&L. Paper only, in code:
  `RoutingExecutionClient` never routes a priced option contract live, whatever the toggle.
  It joins a run only on the default universe and only when Kite or Upstox is connected
  (that is where premiums come from). Not in backtests: there is no premium history to
  replay, so it can never clear the backtest gate. Next: live options orders (the broker
  adapters place NSE equity orders only).
- **2026-09-27, the paper gate (promotion to live).** A strategy switched live routes real
  orders only if it passes the backtest gate *and* its closed paper trades in that user's
  account clear `backend/risk/paper_gate.py`: at least 20 trading days and 30 trades, net
  profit after charges, profit factor at least 1.3, and a drawdown of the strategy's running
  net P&L within 5% of `account_size`. Added to the backtest gate, never replacing it.
  Enforced in `launch_run`; `GET /settings/strategies/promotion` reports each check's need
  and have, and Engine settings shows the gap under each strategy's switch.
- **2026-09-27, live options orders.** `Order.contract` carries the NFO row. Kite places it
  on exchange NFO with its own tradingsymbol; Upstox matches the contract on its option
  chain (underlying, expiry, strike, CE/PE) for the leg's `instrument_key` and refuses when it
  is missing, since Upstox spells option symbols differently from Kite's dump; Angel One
  refuses option orders (`supports_options`). `RoutingExecutionClient` routes an option order
  live only through a broker that supports it. Two sources:
  (1) an option proposal approved live (`POST /suggestions/{id}/approve-live`, a second
  confirming tap in Decisions): claimed as SENDING before the order goes out, refused on a
  kill-switch day, status checked for 5 seconds, a fill booked as `venue="live"` at the
  broker's average price, a broker refusal returns it to PENDING;
  (2) `orb_options`, once switched live and through both gates. For that it can now be
  backtested: `backend/options/backtest.py` lists monthly contracts around spot and prices
  them by Black-Scholes on the last five sessions' 5-minute volatility (no smile, spread or
  liquidity -- optimistic), and `backend/risk/gate_backtest.py` runs any registered strategy
  over a year and records it into the gate -- replacing Phase 4's uncommitted scratch script.
  Admin-only `POST /trading/backtests/{name}` (a link under each strategy in Engine settings
  for an admin) uses the admin's Kite session, whose historical API now fetches a year of
  5-minute candles in 99-day windows; yfinance's ~60 days cannot clear the window. Expect
  `orb_options` to fail: its equity twin `orb_breakout` had profit factor 0.64 in Phase 4.
  Not verified against a real account: neither broker's NFO order path, Upstox's
  `product: "D"` for F&O carry-forward, Kite's per-request history caps (from its docs).
- **2026-09-27, portfolio phases 1-2 (holdings + scorecard).** `get_holdings` on every
  adapter: Kite `holdings()` + `mf_holdings()` (fields from Zerodha's kiteconnect-mocks),
  Upstox `/v2/portfolio/long-term-holdings` (official SDK model), Angel One `getHolding`
  (path from the Python SDK; averageprice/ltp/close in neither SDK, read defensively).
  `backend/portfolio/scorecard.py` (pure) merges by ISIN and computes totals, weights,
  effective number of holdings, sectors (yfinance, cached a month in `instrument_sectors`),
  pairs correlating 0.8+ over a year, and a FIFO lot-by-lot NIFTY comparison from journal
  buys; `service.py` saves each run to `portfolio_snapshots`. `/portfolio` page, linked from
  home. Open, and why: ETF/MF overlap and expense ratios need a holdings/expense data source
  not in the app; ETFs are recognised by name only; Upstox `quantity` vs `t1_quantity` and
  Angel One's price fields need a real account.
- **2026-09-27, portfolio phases 3-5 (health, verdicts, weekly run).** `portfolio/health.py`:
  last four quarters' net profit, ROE, debt/equity, P/E (yfinance), 50/200-day averages,
  distance from the 52-week high, 3-month move, two weeks of headlines; cached per stock per
  IST day in `stock_health`. `portfolio/rules.py`: rules become an Intent scored by
  `composite.py` (sentiment oriented to the verdict, capped at 30%, below the floor a HOLD);
  funds REVIEW/KEEP; loss/size limits are prefs (25% / 20%). `portfolio/review.py` +
  `prompts/portfolio_review.md`: summary and per-holding notes that explain, forbidden from
  telling the reader to trade. `AppSettingsStore.portfolio_verdicts` (admin|all, default
  admin) gates who sees verdicts; `routers/portfolio.py::present` masks them. Friday's
  post-close pass runs `weekly_reviews`: reuses the last holdings repriced from yfinance when
  no broker session is live, alerts (socket + Telegram) only on a verdict that got worse.
  Not done: P/E against the stock's own history, debt trend (only a debt level), fund overlap
  and expense ratios.
- **2026-10-03, AI action plan on the Portfolio page.** `write_review` also returns `plan`
  (improve the mix / sell or trim / add). Stocks to add come only from
  `service.add_candidates`: the user's LONGTERM BUY suggestions from the last 7 days, not
  held, not rejected, best score first, at most 5. So the plan has nothing to add until the
  daily scan runs for that user (`scan_enabled`). Hidden with the verdicts
  (`routers/portfolio.py::present`), so admin-only until SEBI RA registration.

---

### 2026-10-04 — a model per kind of task

Every LLM call names a tier (`fast` / `standard` / `deep`, guarded by
`tests/test_llm_call_tiers.py`); an admin picks each tier's model in Settings → AI and an unset
tier uses the single fallback model. Set from a same-input comparison against Opus on WIPRO,
SJVN and HFCL news: Gemini 3 Flash matched Opus on research reports at 3-4x the speed, but
moved WIPRO's news score from +0.03 to +0.32 and named non-Indian peers for INFY, so news
scoring and peers stay on `deep`. Use unversioned model ids (`agy/gemini-3-flash`): agy
rotates its versioned ids within hours.

### 2026-10-04 — chat assistant over the user's own data

`backend/chat/` replaces the generic ReAct chat (and the unused `POST /chat/message`). Each message
carries a day snapshot; read tools cover portfolio, journal, paper engine, proposals and limits;
action tools only prepare cards, executed by `POST /chat/actions/{id}/confirm` after an atomic claim
and every check again (ad-hoc live orders: NSE equity market, active broker, market open, kill switch
clear, per-trade cap, second tap). Spec and plan in `docs/superpowers/`. Not done: server-side
history, F&O/limit orders from chat; ad-hoc paper orders are not gated by the kill switch.

### 2026-10-04 — the assistant on Telegram, over all of the user's data

The linked Telegram bot is a second client of the same agent: live draft streaming with visible
reasoning and tool steps, Confirm/Cancel buttons, follow-up buttons, `/portfolio` `/proposals`
`/engine` `/limits` `/journal` `/new` `/help`, `/usage` (admins: the Settings usage sheet as one message), and 10 turns of memory. `query_my_data` lets the
agent (web and Telegram) read any of the user's own collections on an allowlist, never secrets or
another user's rows. See ARCHITECTURE.md.

### 2026-10-04 — profile and AI personalisation

`/profile` shows the Google identity and stores a trading profile, preferences, custom
instructions and up to 50 memories in `user_profiles`. Every chat message (web and Telegram)
carries it, so the assistant addresses the trader by name and fits answers to them; it offers
`Remember: …` cards for lasting facts, saved only on Confirm. Spec and plan in
`docs/superpowers/`. Not done: profile in portfolio review/research prompts.

---

## Phase 6 — Revive the long-term agent engine — **done 2026-09-11**

**Goal.** Give long-term suggestions a genuine reasoning source instead of reusing the
intraday rule strategies.

**Work:** rebuild the Analyst/Quant/Risk chain (currently dead —
`backend/components/quant/agent.py`, `backend/components/risk/agent.py`) so it emits
`Intent` and is scored by `backend/scoring/composite.py` like every other source. Its old
`confidence*0.6 + alignment*0.4` blend (`components/risk/agent.py:95-99`) must **not** come
back — that duplicate conviction formula is what the 30% cap exists to prevent. Delete
`backend/components/quant/strategies.py`, whose `TradeSignal` shape is superseded.

**Done when:** long-term suggestions carry agent-derived reasoning in `reason_codes`, the
AI contribution is still capped at 30%, and exactly one conviction formula exists in the
codebase.

### What landed

- **Dead MasterAgent-era code deleted** — the old Analyst/Quant/Risk chain
  (`backend/components/quant/agent.py`, `backend/components/risk/agent.py`) and its
  duplicate `confidence*0.6 + alignment*0.4` conviction blend are gone rather than revived;
  `backend/scoring/composite.py` remains the one conviction formula in the codebase.
- **Analyst-verdict Redis cache** (`backend/ai/analyst_verdict.py`) — `refresh_analyst_verdict`
  runs `AnalystAgent` out-of-band on a new daily scheduler job and caches the result
  (25h TTL); `get_cached_verdict` is the only thing a strategy or scan ever reads, never
  blocking on the LLM call itself.
- **`AnalystVerdictStrategy`** (`backend/strategies/longterm/analyst_verdict.py`) — new
  LONGTERM strategy, BUY when the cached verdict is bullish and clears a materiality
  threshold. Its curated symbol list reuses Phase 5b's F&O `STRIKE_INTERVALS` table
  (`backend/options/resolver.py`) rather than inventing a third curated list — not a
  coincidence.
- **`QualityMomentumStrategy` finally wired into the real `scan_universe` production path**
  — it was registry-ready but dead since it was written; `backend/suggestions/scan.py` now
  actually builds and passes its universe/scores.
- **This fix wave's AI_CAP correction** — `AnalystVerdictStrategy`'s strength formula
  originally let the same LLM sentiment number that feeds `score_intent`'s `ai_score`
  channel also flow into the rule channel unbounded, making `AI_CAP`/`RULE_FLOOR` do
  nothing for this strategy's intents. Fixed to `RULE_FLOOR + AI_CAP * fraction`
  (`backend/strategies/longterm/analyst_verdict.py`) — bounds the rule-channel contribution
  to `AI_CAP`s worth of influence while keeping the "clears the floor by construction"
  property. Also hardened `get_cached_verdict` against a malformed (non-dict) cache
  payload, which previously reached `on_bar`'s hard subscripts and could crash a user's
  entire daily scan for the 25h cache TTL; and bounded/filtered `reason_codes`/`top_reason`
  so an empty or unbounded string can never land in a stored `Intent`.

### Explicitly not done here (deferred, not silently dropped)

- **ATR-based stop widening** — the one piece of the old `RiskAgent` with no current
  equivalent — remains a documented non-goal, not something silently dropped in the
  rebuild.
- **Full daily-cached quality-universe fetch.** `scan_universe` calls
  `build_quality_universe` fresh on every scan (per-user, per-scan yfinance calls) rather
  than caching it once a day the way the analyst-verdict cache does. Out of scope for this
  fix wave; a real follow-up.
- **`owner_by_symbol`'s last-writer-wins in `backend/engine/runner.py`.** When more than
  one strategy is constructed for the same symbol, whichever strategy is built last "owns"
  that symbol for attribution purposes, which can mislabel a non-AI intent with the wrong
  strategy name. Pre-existing bug, predates Phase 6, made more visible by adding a second
  LONGTERM strategy (`analyst_verdict`) that can now collide with `quality_momentum` on the
  same symbol.
- **Orphaned `TradeSignal`/`SignalType` models** in `backend/components/shared/models.py`
  are dead-code cleanup candidates for a future pass — the code that produced them
  (`backend/components/quant/strategies.py`) is already deleted, but the models themselves
  weren't removed in this phase.

---

## Phase 7 — Multi-worker readiness — **done 2026-09-14**

**Goal.** Survive more than one backend worker.

**Work:** Redis pub/sub fan-out for the WS hub (`backend/ws/hub.py:9-10` already flags
this); a distributed lock for the scheduler (`backend/scheduler.py:8-10`); running engine
loops out of the process-local `_RUNS` dict (`backend/routers/trading.py:53`); make the
`llm_service` singleton (`backend/llm.py:125`) request-scoped so the per-user
`omniroute_model` pref stops being dead.

**Done when:** the backend runs with two workers and a user connected to one sees live
updates produced by the other.

### What landed

- **`backend/broadcast.py`** — a new thin wrapper over Redis pub/sub (`publish`/`listen`),
  the one cross-worker primitive everything else in this phase is built on. Degrades to a
  no-op when `redis` is `None` (tests, local dev), same posture
  `backend/ai/analyst_verdict.py`'s `get_cached_verdict` already established for a missing
  cache.
- **`backend/ws/hub.py` fan-out** — `Hub.publish()` always broadcasts through
  `backend.broadcast`; actual per-connection delivery (`Hub.deliver`) happens only in the
  subscriber loop (wired up in `server.py`'s startup), whether that loop lives in this
  process or another one. Falls back to direct local delivery when no Redis is attached.
- **`backend/scheduler.py` distributed lock** — `SET scheduler:daily_lock <token> NX PX
  <2h>` before the daily pass; a worker that loses the race skips the pass rather than
  running it twice. Release is a guarded compare-then-delete so a worker never clears a
  lock some other worker has since acquired after this one's TTL expired.
- **`backend/routers/trading.py` cross-worker cancel** — `stop_background_run` falls back
  to `broadcast.publish("runs:cancel", ...)` when a run isn't in this worker's local
  `_RUNS`; every worker's `handle_cancel_broadcast` cancels a matching local task.
  Fire-and-forget, matching the app's existing best-effort delivery style.
- **Deployment-wide LLM model — short-TTL cache** (`backend/app_settings.py`) —
  `current_llm_model()` is now async and re-reads Mongo at most once every 30 seconds
  instead of relying purely on a local `set_llm_model` write to invalidate it, so a second
  worker sees an admin's change within the TTL window without a restart.
- **Per-user LLM model preference, finally wired up** — `backend/llm.py` gained a
  `contextvars`-based `use_model(...)` context manager; `get_llm()` checks the ambient
  override before falling back to the deployment default. Wrapped around the three real
  per-user call sites (`ws/routes.py`'s `_stream_chat`/`_stream_analysis`,
  `suggestions/thesis.py`'s `attach_theses`) — zero signature changes anywhere in
  `ResearchAgent`, `AnalystAgent`, `analyst/sentiment.py`, `analyst/events.py`,
  `master/search.py`, or `instruments/resolve.py`, confirmed by a clean `git diff` on those
  files.
- Full backend suite: 612 tests passing (up from 600 pre-Phase-7).

### Explicitly not done here (deferred, not silently dropped)

- **No sticky request routing / per-worker port mapping** — cross-worker correctness is
  solved with Redis, not by making requests sticky.
- **No leader-elected price pump.** Each worker keeps polling its own locally-watched
  symbols independently; two workers watching the same symbol poll it twice, an accepted
  cost at this app's current scale, not a defect this phase fixes.
- **No per-user model for `/chat/message` or `/analyze/{symbol}`** (the legacy
  unauthenticated-in-name-only HTTP routes) — both are superseded by the WS-routed
  `_stream_chat`/`_stream_analysis` and have zero frontend callers; stay on the deployment
  default.
- **No per-user model for the scheduler's shared analyst-verdict/sentiment refresh** — that
  value is shared across every user's scan by design, so there is no single user's
  preference that would apply.
- **No confirmation round-trip for cross-worker run cancellation** — the stop broadcast is
  fire-and-forget; a stop that silently misses its target self-heals (the run shows up as
  still RUNNING on next check, or the daily restart clears it).
- **Not yet verified with two real Uvicorn workers + live Redis on the VM.** Everything
  above is unit-tested against mocked Redis; actually flipping `--workers` to more than 1 in
  production and confirming the "Done when" behavior end-to-end is a follow-up smoke test,
  not something this phase's unit tests can prove.

---

## Phase 8 — Reposition as the discipline layer — **done 2026-09-26**

`PRODUCT.md` now leads with the journal, insights, and guardrails, not the strategy engine.
Two reasons, both recorded there: every intraday strategy fails the backtest gate (Phase 4),
and charging for trade ideas needs SEBI Research Analyst registration. Paid features must be
tools that work on the user's own trades and rules, never recommendations.

## Phase 9 — Trade journal MVP — **done 2026-09-26**

**Goal:** every trade a user makes in their broker shows up in NeoTrade without manual entry.

- Add `get_trades()` to `BrokerAdapter` (`backend/brokers/protocol.py`) and implement it in
  all three adapters: Kite `/trades`, Upstox trades-for-day, Angel One `getTradeBook`.
- All three only return **today's** trades. So add an end-of-day sync job (reuse the
  scheduler's Redis lock from Phase 7) and a CSV import of the Zerodha Console tradebook to
  backfill history.
- Trades are stored per user (Phase 1 scoping) and grouped into round trips (entry to exit).
- New `/journal` surface, phone first: P&L calendar, trade list, notes and setup tags.

**Done when:** a connected broker's trades for the day land in the journal after the sync,
a Console CSV import is idempotent (importing twice adds nothing), and `pytest` passes.

### What landed

- `BrokerTrade` (`backend/core/models.py`) and `get_trades()` on all three adapters.
  Kite uses the SDK's `trades()`. Upstox uses `/v2/order/trades/get-trades-for-day`, with
  fields checked against the official SDK's `TradeData` model. Angel One uses `getTradeBook`,
  whose `filltime` is a bare `HH:MM:SS` dated today IST. Timestamp parsing for all of them
  lives in `backend/brokers/trades.py`.
- `backend/journal/`: `store.py` (`journal_trades`, `_id` = user:broker:trade_id, so syncs
  and imports never duplicate; `journal_notes`), `roundtrips.py` (pure flat-to-flat
  grouping per broker+exchange+symbol, splits a fill that crosses zero, plus the daily
  calendar), `console_csv.py`, `sync.py`.
- `backend/routers/journal.py`: `GET /journal`, `POST /journal/sync`,
  `POST /journal/import/zerodha-console` (CSV text in a JSON body, so no multipart
  dependency), `PUT /journal/round-trips/{id}/note`.
- The 16:00 IST daily pass now syncs every user's connected brokers (`scheduler.py`
  `_sync_journals`).
- `frontend/src/pages/Journal.jsx`: month calendar of daily P&L, round-trip list, per-trip
  note and tags, sync and CSV import buttons. Added to the nav as "Journal".

### Known limits

- **Live broker sync has never run against a real account.** Same posture as every other
  adapter: the mapping is verified against docs and SDK source only. Upstox's
  `exchange_timestamp` format is only documented as "user readable", so more than one
  format is accepted.
- P&L is **gross**. No broker's trade book carries brokerage, STT or exchange charges.
- A round trip's id is its first fill's id. Backfilling *older* fills for the same symbol
  can regroup trips and detach a note from the trip it was written on.
- `GET /journal` loads a user's whole history on every call (`ponytail:` comment in
  `store.py`). Page it by date once anyone has tens of thousands of fills.
- Only Zerodha Console's CSV is importable. Upstox and Angel One exports are not wired up.
- **2026-10-03:** Upstox history by API instead of a CSV: `UpstoxAdapter.get_trade_history`
  (`/v2/charges/historical-trades`, EQ + FO, paged; checked against upstox-python-sdk 2.30.0
  only) and `POST /journal/import/upstox-history` (default a year, fetched a month at a
  time), an "Import Upstox history" button in the journal. Rows carry a date and no time, so
  fills are stamped 09:15 IST: daily P&L holds, intraday trip order within a day does not.
  Days already filled by the live sync are skipped, since the two may number fills
  differently. `trade_date` format is a guess list until a real response is seen.

## Phase 10 — Behaviour insights — **done 2026-09-26**

**Goal:** tell the user, in plain language, which of their habits cost them money.

- Aggregates over journal round trips: P&L by time of day and weekday, trades after N
  losses in a row, size after a loss vs normal, holding time, win rate per setup tag.
- Shown as findings with the ₹ amount, e.g. "Trades after 2 losses in a row: win rate 31%,
  −₹8,400". No scores, no streaks, no celebration (`PRODUCT.md` brand rules).

**Done when:** each finding matches a hand-computed value on a fixture journal.

### What landed

- `backend/journal/insights.py`: pure `build_insights(trips)` over closed round trips,
  returned as `insights` in `GET /journal`. Each finding is one group of trades set against
  every other closed trade: trades, P&L, win rate, average P&L, and the same for the rest.
- Findings: worst and best time-of-day bucket, worst and best weekday, trades opened after
  2+ losses in a row that day, the 4th and later trades of a day, position size right after
  a loss (reported only at 1.25× usual or more), losers held 1.5× as long as winners or
  more, and one per setup tag.
- A group needs at least 5 trades (`MIN_TRIPS`) before it is shown. Sorted costliest first.
- `backend/tests/test_journal_insights.py` checks every kind against hand-computed values.
- The Journal page shows them as "Your patterns", between the calendar and the trade list.

### Known limits

- Same gross-P&L caveat as Phase 9.
- "That day" streaks and trade numbers reset at the IST date boundary, so overnight
  positions count on the day they opened.
- The thresholds (5 trades, 1.25×, 1.5×) are judgement calls, not tuned on real users.

## Phase 11 — Guardrails — **done 2026-09-26**

**Goal:** enforce the limits the user set for themselves.

- Per-user rules: daily loss cap, max trades per day, cooldown after N losses.
- Watch live positions through the existing WS feed. When a rule trips, alert the user
  (Telegram bot or web push) and optionally square off, reusing
  `backend/risk/kill_switch.py` and `place_order`.
- Honest limit, stated in the UI: NeoTrade **cannot block** orders placed in the broker's
  own app. It can only alert and square off.

**Done when:** a rule trips in paper mode, the alert reaches a phone, and auto square-off
works on paper before it is ever enabled live.

### What landed

- `backend/guardrails/rules.py`: pure `evaluate(trips, day_pnl, prefs)`. Daily loss uses the
  existing `daily_loss_limit` against the broker's own day P&L (realised + unrealised over
  its position book). New prefs: `guardrails_enabled` (default off), `max_trades_per_day`,
  `cooldown_after_losses`, `cooldown_minutes`. 0 turns a rule off.
- `backend/guardrails/monitor.py`: once a minute, 09:15–15:35 IST on weekdays, one worker
  per tick (Redis `SET NX` lock). For each opted-in user it syncs today's trades into the
  journal, evaluates, and alerts each new breach once (`guardrail_events`, keyed per user +
  day + breach). A daily-loss breach also trips `KillSwitchStore` for the day.
- Alerts go over the socket (topic `guardrails`, shown on the Journal page) and to Telegram
  when linked (`backend/guardrails/telegram.py`, `backend/routers/guardrails.py`). Linking
  uses a t.me deep link with a one-time code plus `getUpdates`, so no webhook is needed.
- Settings has a Guardrails sheet. `backend/tests/test_guardrails.py` covers the rules, the
  once-only alert, the kill-switch trip, the lock, and the session window.

### Not done, deliberately

- **Auto square-off, added 2026-09-26 on the user's explicit choice.** Pref
  `auto_square_off`: `off` (default), `preview` (alert with the exact exit orders, send
  nothing), `live` (send them; Settings asks for confirmation first and the Guardrails
  header says "square-off live"). On a daily-loss breach, `backend/guardrails/square_off.py`
  turns each ACTIVE broker's position book into MARKET exits. Limits: only NSE + MIS, since
  every adapter's `place_order` is NSE-cash-only and delivery/F&O exits are not a
  same-session decision; anything else is named as "Not touched". At most once per day: it
  hangs off the `daily_loss` breach record, which is written before any order goes out.
  Failed orders are reported as "close these yourself". `Position` gained `exchange` and
  `product`, filled by all three adapters' `get_positions`. Covered by
  `backend/tests/test_square_off.py`. **This is the one path that places a real order
  without a per-trade approval, and it has never run against a live account.** Use
  `preview` on a real account first and check the orders it reports are right.
- **Telegram needs a human step.** Create a bot with @BotFather and set `TELEGRAM_BOT_TOKEN`
  in the deploy clone's `.env`. Until then Settings says Telegram is not set up and alerts
  stay in the app.
- **Never run against a live broker**, same as Phase 9.

## Phase 12 — Free beta

Not code. Recruit 20–50 traders (r/IndianStreetBets, r/IndiaInvestments, fintwit, Telegram
groups). Track weekly-active users and whether people open the journal after a losing day.
If they don't come back weekly, fix the product before building Phase 13.

### Tooling landed 2026-09-26

- `backend/journal/beta.py`: every `GET /journal` records one `journal_opens` document per
  user per IST day. `GET /journal/beta-metrics` (admin only) returns sign-ups, users with
  trades, weekly active, how many of last week's active users came back, guardrails on,
  Telegram linked, and losing days followed by a journal visit within 3 days. Settings shows
  it to admins as the "Beta" sheet.
- The login page now says what the product does (journal, patterns, guardrails) and that
  it is not advice and holds no money. The old "paper trading only" line was stale.

### Onboarding friction to know before recruiting

- **Broker API keys are per user.** Connecting Kite, Upstox or Angel One means each trader
  creating their own developer app and pasting its key into Settings. Most won't. The
  Zerodha Console CSV import is the realistic first step for a beta user; lead with it.
- **Google sign-in** only lets in listed test users while the OAuth consent screen is in
  "Testing" mode. Check it is published before inviting strangers.

## Phase 13 — Billing + real domain

- A real domain replaces `nip.io` (needed for Razorpay KYC and user trust). Add privacy
  policy, terms, and refund policy pages.
- Razorpay Subscriptions. Free: 1 broker, 30 days of journal. Pro (around ₹299–499/month):
  unlimited history, insights, guardrails, multiple brokers.
- Before launch, check Kite Connect's current fees and its rules for multi-user third-party
  apps. Upstox and Angel One APIs are free.

### 2026-10-04 — evidence-based core strategy (factor portfolio) on paper

The engine's per-symbol strategies have no edge (intraday PF 0.64–0.91; long-term never
backtested), and the backtester itself was flattering them. Plan:
`/home/ubuntu/.claude/plans/iridescent-munching-cherny.md`.

- Backtester honesty: metrics net of charges, 10 bps slippage per side, intraday stamp duty
  fixed (`engine/backtest.py`, `execution/simulated.py`, `execution/costs.py`).
- `backend/factor/`: Nifty 200 momentum (6/12m skip-1m ÷ vol) + low-vol, top N with a rank
  buffer, inverse-vol capped weights, vol-targeted, risk-off below the Nifty 200-DMA. Daily
  mark-to-market backtest that trades the day after deciding; 8-variant walk-forward
  (3y in-sample → next year) and Deflated Sharpe counting all 16 variants ever tried.
  `python -m backend.factor.report`.
- Result, out-of-sample 2012-01 → 2026-10, net: **21.8% CAGR, Sharpe 1.59, max DD −15%**
  vs Nifty 200 12.8% / 0.83 / −38%; DSR 1.00 — passes. Caveat: today's members over past
  years (survivorship); equal-weight of the same names: 24.6% / 1.37 / −38%.
- Paper: `backend/factor/paper.py`, its own `factor_paper_capital` (₹3 lakh) book,
  rebalanced at the first 09:20 pass of each month. Per-symbol proposals are no longer
  auto-bought. Risk-off sleeve modelled as cash at a liquid-ETF yield (LIQUIDBEES has no mark).
- Next: intraday experimental/off for new users; discipline mirrors (costs, benchmark,
  edge by setup); live only after 3 months of paper beating the benchmark.
- Live (Phase E) is deliberately not wired for the factor portfolio. It goes live only when
  all hold: `python -m backend.factor.report --save` passes; the paper book has run ≥3
  months and beats the Nifty since it started (`book_return` > `nifty_return`, reported in
  every monthly rebalance message); and the user opts in, starting small. Live needs real
  LIQUIDBEES orders for the risk-off sleeve (no instrument-master mark today).
- Journal mirror (`backend/journal/mirror.py`): estimated charges, P&L after them, trades/yr
  vs SEBI's 500 line, return vs Nifty — Journal calendar tab, AI `get_journal`, Friday Telegram.

### 2026-10-04 — learning loop: the paper engine learns from its own closed trades

Statistics decide, the LLM explains. Plan: `/home/ubuntu/.claude-second/plans/jolly-pondering-peach.md`.

- Every order now carries `context` (strength, reason_codes, composite score), copied onto the
  trade it opens. Older trades borrow it from their approved suggestion.
- `backend/learning/attribution.py`: closed paper trades net of charges, per strategy, grouped
  by reason code, Nifty regime at entry (vs 200-DMA) and strength bucket; ≥10 trades per
  group; expectancy also shrunk toward 0 (10 pseudo-trades) so small lucky groups don't count.
- `backend/learning/adapt.py`, nightly in the daily pass (`scheduler._learn`): **pause** a
  strategy losing (shrunk < 0, PF < 1) over ≥30 trades — it resumes only on a newer passing
  backtest gate result and is then judged from that day; **raise its own strength floor** by
  ≤0.05 a night (cap 0.8) while weak signals lose and stronger ones don't; **skip a losing
  regime**. `size_intents` applies them to entries only, never exits. Every change goes to
  `learning_changes` (before, after, evidence); current rules in `learning_state`.
- `backend/learning/report.py`: Friday Telegram note (prompt `learning_review.md`, standard
  tier, figures-only fallback) and the chat tool `get_learning`.
- Monthly re-tune (`backend/learning/retune.py`): each strategy declares `PARAMS` and a small
  `GRID` (`strategies/base.py`). The first daily pass of a month starts
  `nice python -m backend.learning.retune` as its own process. Per daily-bar strategy, over the
  last 3 years: every variant is backtested on the first 2 years, the best by net Sharpe
  (≥20 trades) is re-run with the current params on the last year (300 days warmup, only
  trades after the split count). It replaces the current params only if it makes money
  there, beats them, and its Deflated Sharpe ≥0.95 counting every variant ever tried for that
  strategy. Every attempt goes to `strategy_retunes`; the latest accepted one is what runs,
  scans and gate backtests use. Intraday strategies are not re-tuned: yfinance's ~60 days of
  5-minute bars leave too short a test window to pass (needs a year of Kite history).
- Backtester fix found on the way: long-term buys are now sold at the close that crosses
  their stop or target (as paper does). Before, nothing sold them and their P&L never showed.
- LLM hypotheses (`backend/learning/hypotheses.py`, prompt `strategy_hypotheses.md`, deep
  tier): at the start of each monthly re-tune the model sees each daily strategy's current
  thresholds and grid, the last re-tune's in-sample results and every user's worst paper
  setups, and may suggest up to 3 new threshold values. Only known keys of re-tunable
  strategies, numbers within ¼×–4× of what runs now, not already in the grid. Each is queued
  in `strategy_hypotheses` and, in the same run, tested exactly like a grid variant (unseen
  year, must make money and beat what runs, Deflated Sharpe counting every variant and idea
  ever tried). The model never changes anything itself. Shown in Journal → Engine learning.
- Journal → Engine learning tab (`GET /journal/learning`): rules, changes, setups, re-tunes,
  hypotheses.
- Not done: intraday re-tune from Kite history. Known weakness: the model sees paper trades
  that overlap the test year, so its ideas are not fully out of sample — the Deflated Sharpe
  counting each idea is the guard.
- Intraday re-test under the honest backtester (2026-10-04: net of charges, 10 bps slippage,
  stop/target exits; yfinance 5m, 56 days, 80 of 83 symbols). All lose before charges too:

  | Strategy | Trades | Win | PF (net) | Max DD | Sharpe | Gross | Charges | Net |
  |---|---|---|---|---|---|---|---|---|
  | volume_surge | 365 | 0.36 | 0.73 | 14.6% | −5.90 | −₹89,063 | ₹26,909 | −₹1,15,972 |
  | vwap_reversion | 125 | 0.38 | 0.80 | 20.7% | −2.31 | −₹1,35,376 | ₹19,188 | −₹1,54,563 |
  | orb_breakout | 174 | 0.29 | 0.63 | 28.1% | −3.95 | −₹2,07,665 | ₹22,379 | −₹2,30,044 |
  | rsi_momentum_scalp | 82 | 0.28 | 0.73 | 21.5% | −2.45 | −₹1,60,846 | ₹13,223 | −₹1,74,070 |

  Intraday stays experimental. The runner is slow (~125 bars/s, ~30 min per strategy over
  235k candles): strategies recompute indicators per bar.
