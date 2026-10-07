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
| 14 | Shared market, macro & news data layer (`backend/datalayer/`, `ingest` container) | — | **done** (broker ticks into `quote:` left for later) — 14.0 worker + leader lock + `/health`, 14.1 quotes + macro loops, 14.2 news ingest/triage/scoring/sentiment, 14.3 calendar/flows/regime/brief + chat/report/index wiring, 14.4 news alerts (Telegram + toast), News page, Today markets card, 14.5 news-triggered scans (`source="news"` proposals), 14.6 autopilot news entries + regime fence (exits shadow-logged), 14.7 news outcomes + theme weights (weights fill after ~3 weeks of data), 14.8 shared `daily_bars` + `fundamentals` stores (scan, scanner, quick analysis, portfolio, NIFTY benchmarks read them; per-worker caches deleted) done 2026-10-05; plan `docs/superpowers/plans/2026-10-05-market-news-datalayer.md` |
| 15 | AI game plan + strategy library + news across the app (15.1 library + 4 strategies, 15.2 plan core + replay scorecard, 15.3 revisions, 15.4 surfacing) | 14 | **15.1 done 2026-10-05** (cards, live library + `/strategies/library` + chat tool, 4 news-aware intraday strategies on paper); **15.2 done 2026-10-05** (08:45 per-user plan, validator + fallback, PlanGate in `size_intents`, skip-day, nightly plan-vs-no-plan replay); **15.3 done 2026-10-05** (event-driven revisions in ingest, plan exits with live ones shadow-only, mid-session stocks in play with backfill); **15.4 done 2026-10-05** (news chips on holdings/watchlist/scanner/decisions via `GET /news/symbols`, journal news findings, Today's plan card on AI → Activity via `GET /plan/today`, Practice → Library page, Telegram plan summaries). **Phase 15 done.** — spec `docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md`, plan `docs/superpowers/plans/2026-10-05-strategy-library-plan.md` |
| 16 | AI on tools: shared fact layer, capped tool runner, grounding check (16.1 facts+runner+grounding+chat, 16.2 plan, 16.3 analyst, 16.4 review/index/learning, 16.5 single-call sites on facts) | 15 | **16.1 done 2026-10-06** (13 facts in `backend/ai/facts/`, `ai/runner.run_with_tools`, `ai/grounding`, chat read tools on facts); **16.2 done 2026-10-06** (plan builder + revisions on tools, grounded rationale, single-call fallback); 16.3–16.5 not started — spec `docs/superpowers/specs/2026-10-06-ai-tools-fact-layer-design.md` |
| 17 | Profitability and LLM cost: measure before spending, trade only where there is evidence (17.1 fix what corrupts the evidence, 17.2 LLM cost, 17.3 edge, 17.4 architecture, 17.5 business) | 14–16 | **17.1 done 2026-10-07** (auto intraday waits for a live broker feed, stale seed symbols dropped, untagged approvals refused, long-term gate backtests re-run, Today net of charges, plan replay fixed); 17.2–17.5 planned |

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
another user's rows. See the handbook, `frontend/src/handbook/ai-and-news.md`.

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

### 2026-10-04 — two broker accounts: AI autopilot (Kite) and the user's own (Upstox)

Roles per broker, role-based routing with no fallback, per-account analysis (portfolio,
journal, chat, AI-vs-you monthly), AI-proposed exit/cancel/modify/stop-loss cards on the user's
account, and a fenced autopilot on the AI account (paper by default; live behind a typed
confirmation). The autopilot is a documented, user-approved exception to the backtest gate and
to "model output never places an order" (AGENTS.md, .claude/CLAUDE.md). Spec and plan in
`docs/superpowers/`. Setup: Kite Connect app; static IP 161.118.167.148 whitelisted with Zerodha
and Upstox; daily logins (09:00 reminder).

## Phase 17 — Profitability and LLM cost — planned 2026-10-07

Written from a whole-system scan on 2026-10-07 (code, prod data, the backup at
`~/backups/neotrade/20261006T183548Z/`, OmniRoute's `usage_history`). Every claim below
names the number it rests on.

### Where things stand (the evidence)

- **No strategy has an edge after charges except the factor portfolio.** Every intraday
  gate backtest fails: profit factor 0.63–0.91 over 82–509 trades (volume_surge 0.73,
  vwap_reversion 0.80, orb_breakout 0.63, rsi_momentum_scalp 0.73). The four news-aware
  intraday strategies have never been backtested. The factor portfolio passes out of
  sample (21.8% CAGR, Sharpe 1.59, max DD −15%, 2012–2026, survivorship caveat).
- **Charges are larger than the edge.** Paper intraday, 21 trades: +₹33.6 gross, ₹104.5
  charges. With a ₹25,000 account and ₹5,000 per-trade cap, the median ticket is ~₹4,900
  and round-trip charges are ~0.11% of it — more than the 0.05–0.10% a typical intraday
  rule earns before costs.
- **Long-term approvals lost money untracked.** 11 long-term paper trades lost ₹16,780
  gross (₹19,376 net) and carry no `strategy`, so no strategy was judged on them.
- **The paper record was corrupted for a week.** 32 of 50 intraday runs (26 Sep–2 Oct)
  died on one stale ticker, `GMRINFRA.NS`; the runner now skips a bad symbol (fixed
  2026-10-05) but `backend/instruments/seed_nse_equity.json` still lists GMRINFRA.
- **Paper intraday trades on 15-minute-old candles.** Every recorded run used
  `yfinance 5m, ~15 min delayed`: the feed is picked once at 09:15, and the Kite (`ai`)
  session is not logged in yet then, so the run never upgrades to live ticks.
  Results from delayed bars say nothing about a live strategy.
- **The game plan was never measured.** `plan/replay.py` read a `runs` collection that
  does not exist (runs live in `trading_runs`), so `plan_scorecards` stayed empty.
  Fixed 2026-10-07 (a9a2b09); scorecards start with the next 16:00 pass.
- **News sentiment is unproven.** `news_outcomes` has 20 scored moves so far; the
  direction called by the scorer matched the next-day move 30% of the time. Too few to
  judge, not yet a signal — yet it is 30% of every composite score and `autopilot_news`
  is on.
- **LLM use.** ~200–340 calls a day since 2026-10-03 (21/day before), 5.5M tokens and
  $6.47 this month on the gateway key. **All three tiers point at the same model,
  `gemini-3.7-flash-high`**, so headline triage reasons like a plan: average output
  ~4,900 tokens, about half of it reasoning. 114 calls went to
  `claude-opus-4-6-thinking`, whose shared pool is down to 10%. The binding cost is
  quota and latency (10 s average), not dollars — until there are more users, when
  per-user calls (game plan ~20 deep calls a day per auto-intraday user, chat,
  portfolio review) multiply.

### 17.1 Stop corrupting the evidence (first, small)

1. **Live feed or no intraday paper run.** Start the auto run when the `ai` broker
   session becomes ACTIVE (on login, not only at 09:15), and swap a running candle-poll
   feed for broker ticks when the session arrives. A day with no live session runs no
   intraday paper (logged as "no live feed"), so the record only holds live-like days.
   `backend/engine/autorun.py`, `backend/routers/trading.py::build_feed`.
2. **Stale instruments.** Refresh `seed_nse_equity.json` from the live NSE list and add a
   rename map (GMRINFRA → GMRAIRPORT …) applied to stored universes; a symbol that fails
   its first quote is dropped from the run with a warning (already the runner's behaviour).
3. **Every paper trade carries its strategy.** Refuse an approval without `strategy`;
   backfill none (history was reset 2026-10-06).
4. **Long-term backtests work.** `technical_breakout`'s gate backtest made 5 trades with
   ₹0 P&L — the long-term backtest path does not close positions for it. Fix, then run
   gate backtests for every long-term strategy and the four untested intraday ones
   (a year of Kite 5-minute history).
5. **One money rule on Today.** Mine shows "closed, gross" beside AI's figure; show both
   net of estimated charges (the journal mirror already estimates them).

**Landed 2026-10-07:** c67fd89 (auto run waits for Kite/Upstox ACTIVE), 289a1a1 (GMRINFRA,
GSPL, GUJGASLTD, TATAMOTORS, TATAMTRDVR out of the seed and the master), ae6d319 (409 on
approving a proposal with no strategy), d593019 (Today's Mine and AI net of charges),
a9a2b09 (plan replay reads `trading_runs`). Long-term gate backtests re-run on today's
code (the ₹0 technical_breakout rows predated the stop/target fix): technical_breakout
97 trades PF 0.71, mean_reversion 65 PF 0.74, macd_crossover 89 PF 0.87 — all fail.
cash_secured_put made 0 trades (needs Kite's NFO lot sizes). Still to run with a Kite
session: a year of 5-minute history for the four news-aware intraday strategies, and
quality_momentum / analyst_verdict through the scan harness.

Done when: a week of intraday paper runs all record `live broker ticks`; every closed
paper trade has a `strategy`; every registered strategy has a gate backtest row; the
first `plan_scorecards` rows exist.

### 17.2 Cut LLM cost by matching the model to the job

1. **Three tiers, three models.** `fast` = a non-reasoning flash/haiku model (triage,
   follow-ups, name resolution); `standard` = flash with low reasoning (brief, research
   note, learning note, index move); `deep` = flash-high only for news scoring and the
   plan. Opus-class models only for the chat when the user asks for depth. Expected:
   roughly half the output tokens disappear from fast and standard calls, and latency
   drops from ~10 s.
2. **Score less news.** Before the deep scoring call: drop near-duplicate headlines
   (same story, many feeds — cluster by normalised title), and drop items whose tags
   touch no followed symbol, no followed sector and not the market. Keep the 200/day cap.
3. **Brief only when something changed.** Hourly in session instead of every 30 min,
   and skip a slot when no material item and no regime change happened since the last
   brief.
4. **Plan only when it can matter.** Build the game plan only on days the intraday
   auto-run will actually run with a live feed and only for strategies not paused;
   revisions ≤ 2 a day (now 6); tool rounds ≤ 2 (now 4). If after four weeks
   `plan_scorecards` shows the plan does not beat no-plan net of charges, switch plans off.
5. **Meter per feature.** One OmniRoute key per task family (news, plan, research,
   chat, portfolio) so `usage_history` splits by `api_key_name`; show it on the
   handbook's AI panel with a per-feature daily budget and an 80% alert.
6. **Cache what repeats.** Research notes are per symbol already — share them across
   users explicitly; cache index-move explanations per ticker per session (15 min now);
   turn on OmniRoute's semantic cache for the read-only explainers.
7. **Per-user ceiling before the beta.** A daily per-user budget for chat and research
   calls, with the shared pipeline (news, brief, regime) amortised across everyone.

**Landed 2026-10-07:** tiers set in `app_settings` — fast `kr/claude-haiku-4.5` (no reasoning,
1.7 s, 2 output tokens on a triage probe; Kiro adds ~4k prompt tokens a call), standard
`agy/gemini-3.7-flash-low`, deep `agy/gemini-3.7-flash-high` (no non-reasoning Gemini is in
the live catalog). News: `_prune` drops rewrites (title overlap ≥ 0.7 within a day), company
news with no followed symbol and non-Latin copies before the deep call — ~10% of 3 days'
2,443 scored items. Brief: hourly in session, skipped unless the regime moved or material
news landed. Plan: built only once the user has a live broker feed (the auto run's own
check; window now 08:45 to the close, so a late login is planned before its run starts), paused
strategies left out (all paused → fallback, no call), revisions ≤ 2 a day, tool rounds ≤ 2. The
four-week plan-vs-no-plan review in 17.2.4 is still to do once `plan_scorecards` fills.
Per feature: six OmniRoute keys ("NeoTrade news/plan/research/chat/portfolio/learning") in
`OMNIROUTE_FEATURE_KEYS`; every call site names its feature (pinned by a test); a feature
key never falls back to the shared one, so a daily USD limit on it is the feature's budget;
the handbook's AI panel shows each key's tokens and cost with ⚠ at 80%. **Limits not set
yet** — set them in OmniRoute after a week of per-key data (~2026-10-13). 17.2.6: research notes were already one per symbol for every user (`analyst:<SYM>`, 4 h);
index explanations moved from a per-worker dict to Redis (shared by both workers), 15 min
while the session is dated today, then until the next 09:15 IST open (≤ 6 h); OmniRoute's
response cache was already on for every key (303 hits / 3,083 misses so far — explainer
prompts carry live figures, so exact repeats are rare). 17.2.7: `USER_LLM_CALLS_PER_DAY` (150) counts each chat/research
LLM call made inside a user's own chat (web, Telegram) or AI analysis; cache hits and the
shared pipeline never count; past it the user is told plainly. Suggestion theses and the
weekly portfolio review are not counted (scheduled, rate-limited at the scan).
Remaining for 17.2's done-when: per-key daily limits (~2026-10-13) and a month-on-month token
comparison.

Done when: calls per day and tokens per call are visible per feature, fast-tier calls
average under 500 output tokens, and the month's tokens fall by at least half at the
same feature set.

### 17.3 Make money where there is evidence

1. **Put the capital behind the factor portfolio.** It is the only strategy with
   out-of-sample evidence. Fix its survivorship bias first (point-in-time Nifty 200
   membership), keep it on paper until its own gate holds (3 months, beats Nifty since
   start), then go live small through the AI account — monthly rebalances on delivery
   (CNC) cost little next to intraday.
2. **Park intraday.** Turn `auto_paper_intraday` off until one intraday strategy passes
   its gate on a year of Kite history; nothing intraday trades real money before both
   gates (unchanged rule). Raise the bar for intraday: profit factor ≥ 1.3 *after*
   charges at the ticket size the account actually uses.
3. **Size for the charges.** At ₹25,000, ₹5,000 tickets pay ~0.11% round trip. Either
   trade fewer, larger tickets (long-term/factor) or accept that intraday cannot clear
   costs at this account size. (`size_intents` already skips an intent whose expected
   gain is under `COST_MULTIPLE = 3` × its charges — `backend/engine/runner.py`; keep it,
   and report how many intents it drops so the effect is visible.)
4. **Prove news before it moves money.** Keep the 30% cap, but turn `autopilot_news` off
   and weight news by its measured hit rate per theme (theme weights already exist)
   once `news_outcomes` has ≥ 200 rows; if the hit rate stays at or below 50%, set the
   AI share to 0 for that theme.
5. **Long-term proposals: fewer, better.** Expire after 3 days (as now), but show only
   the top 5 by score with a minimum expected move after charges; 27 pending is noise
   nobody reviews.
6. **Autopilot stays off** until a strategy on the AI account has passed both gates.

**17.3.1 survivorship, measured 2026-10-07** (`python -m backend.factor.survivorship`). No free
point-in-time Nifty 200 membership exists (niftyindices.com no longer serves history; ~28
NSE reconstitution circulars plus missing prices for delisted names would still leave gaps),
so the bias was measured, not removed:

| Yardstick | Ours (today's list) | Survivorship-free | Gap |
|---|---|---|---|
| Equal weight vs `^CNX200`, 2012–2026 CAGR | 24.1% | 12.5% (price index) | +11.6%/yr |
| Momentum-30 setup vs ABSL Nifty 200 Momentum 30 ETF, 2022-08..2026-10 | 16.6% | 8.8% | +7.9%/yr |
| Low-vol-30 setup vs `LOWVOLIETF` (Nifty100 Low Vol 30), 2018-05..2026-10 | 14.7% | 11.2% | +3.6%/yr |

The gap is not concentrated in early years (2020–2024: +17% to +30% a year on equal weight),
so it is mostly *inclusion* bias — today's members are there because they rose — plus
dividends (~1.3%/yr, in our adjusted closes, not in `^CNX200`) and methodology differences.
The shipped strategy shows 19.0% CAGR / Sharpe 1.60 / max DD −16% on today's data;
less 4–8%/yr of bias that is ~11–15%, against ~14% for the Nifty 200 with dividends. **The
backtest is no evidence of an edge.** The forward paper gate (3 months, beats Nifty since
start) is the only evidence that counts; no live capital before it holds.

**Status 2026-10-07:** 17.3.3 landed: each run counts entries dropped by the cost check
(`progress.below_cost`, shown on the engine card). 17.3.2's bar was already in code: gate
backtests are net of charges and sized with the user's own `account_size`/`per_trade_cap`,
PF ≥ 1.3. The owner kept `auto_paper_intraday` and `autopilot_news` on (asked 2026-10-07).
17.3.5 landed: after each scan only the 5 best pending long-term proposals by final score
stay (the rest expire as `outranked`); the minimum-move rule was already `size_intents`'
3× charges check. 17.3.4 landed: with 127 measured 1-day outcomes (64% hit overall),
the autopilot takes a news proposal only when its impact's themes are *proven* —
measured (≥ 20 outcomes for that scope, theme and direction) with a mean weight above 1,
i.e. hit rate over 50% (`outcomes.proven`, `reactor.ai_targets`); unmeasured or losing
themes stay proposals for the user. Owner chose proven-only over blocking just the losers.
At landing: COMPANY earnings ↑ 83% (n 54) and growth ↑ 72% (n 65) proven, COMPANY deal ↑
45% (n 20) blocked.

Done when: the factor book has 3 months of paper beating Nifty; intraday is off or
gated by a passing year-long backtest; no trade is sized whose expected move does not
clear 3× charges.

### 17.4 Architecture

1. **One evidence ledger.** Every decision (engine proposal, plan change, news alert,
   autopilot order, user approval) writes one row with its inputs and, later, its
   outcome net of charges — the same shape `news_outcomes` uses. The learning loop,
   plan scorecard, strategy record and news hit rate become queries on one table
   instead of four bespoke stores.
2. **Feature switches with a cost line.** Each LLM-backed feature (news scoring, plan,
   brief, research, portfolio review, chat) gets a switch and its monthly token cost on
   the handbook page, so turning something off is a decision with a number beside it.
3. **Data quality as a job.** A nightly check: instruments that failed a quote, symbols
   in universes no longer listed, bars older than a day in session, feeds silent for
   an hour — reported on the handbook's Jobs panel.
4. **Point-in-time data.** Index membership and fundamentals as of the backtest date,
   so backtests stop flattering today's survivors.

**17.4.2 landed 2026-10-07:** an On/Off switch per LLM feature beside its cost on the
handbook's AI panel (`POST /settings/llm-feature`, `app_settings.llm_features_off`); off, the
feature makes no model calls and each caller takes its "LLM disabled" path (news skips its
LLM pass, the learning note falls back to plain facts).
**17.4.3 landed 2026-10-07:** `backend/system/data_quality.py` after the 16:00 pass — stale
daily bars, unlisted universe symbols, feeds silent 3 days — on the Jobs panel. "Bars older than
a day in session" is covered by stale bars (the pass runs after the close); feed silence is
3 days, not an hour, because the official feeds (RBI, SEBI, PIB) post rarely.
17.4.4 (point-in-time data): no free source — see 17.3.1.
Its first run found `mc_latest`/`mc_reports` silent: every Moneycontrol RSS feed froze on
23 Apr 2024 (and 403s a browser UA), so both were replaced by Business Standard and
BusinessLine markets feeds. **17.4.1 (evidence ledger) deferred** (owner, 2026-10-07): revisit
after the plan review (~2026-11-03) or before the beta, once there is evidence to unify.

### 17.5 The business

The product is the discipline layer (journal, habits, guardrails), not the engine. The
engine earns its keep by being honest, and costs little once 17.2 lands. Before more
engine work: Phase 12 (beta, 20–50 traders). Keep paid features LLM-light (journal,
insights and guardrails make no model calls), and target an LLM cost per active user per
month that the Pro price (₹299–499) covers many times over.

### Order

17.1 → 17.2 (both small, both protect everything after them) → 17.3.1–17.3.3 →
Phase 12 beta → 17.4 → 17.3.4 once news has data → Phase 13.
