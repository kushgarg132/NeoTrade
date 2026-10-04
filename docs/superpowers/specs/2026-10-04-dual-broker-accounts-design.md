# Two broker accounts: an AI account (Kite) and the user's own (Upstox) — design

Date: 2026-10-04. Status: approved in chat, awaiting spec review.

## Goal

The user wants two broker accounts with different owners:

- **Kite = AI account.** The engine and the AI place orders here by themselves, inside hard limits.
- **Upstox = the user's account.** The user trades. The AI may only *propose* changes, and each one
  reaches Upstox only after the user confirms (plus a second tap for live orders, as today).
- **Analysis for both:** each account on its own, both together, and the AI's results against the
  user's.

Success: an AI order can never reach Upstox, and a user-account action can never reach Kite. The Kite
autopilot cannot exceed its capital, per-trade, daily-trade or daily-loss limits. The user can stop
it in one tap. Every screen and tool can answer "how is my Upstox doing" and "how is the AI doing
on Kite", separately and together.

## Today (from the code)

- Credentials are stored per user per broker (`auth/broker_credentials.py`). Kite, Upstox and Angel
  One can be connected side by side.
- Live routing uses whichever broker has an ACTIVE session first, in `BROKERS` order
  (`routers/trading.py:get_active_broker_adapter`; also `chat/actions.py:_active_broker`). It has
  no roles.
- Holdings and journal trades already carry `broker`. The portfolio (`portfolio/service.py`, which
  stores `brokers` on snapshots) and the journal merge all brokers into one view.
- Adapters (`brokers/protocol.py`) support `place_order`, `cancel_order`, `get_positions` and
  `get_holdings`. There is no `modify_order` and no stop-loss trigger order yet.
- Project rules (`AGENTS.md`, `.claude/CLAUDE.md`): model output may propose but never place an
  order; live orders need a second confirmation; the kill switch and backtest gate are never
  routed around.

## Decisions

- **Roles per connected broker:** `ai` (autopilot may trade), `mine` (AI proposes, user confirms),
  or unset. At most one `ai` account. Kite is `ai`, Upstox is `mine` for this user.
- **Routing by role, never by fallback.** If an action's target role is missing or its session is
  not ACTIVE, the action is refused with a clear message. It never falls back to the other account.
- **Kite autopilot = fenced** (the user chose the recommended guardrails). It is an **explicit,
  user-approved exception** to "model output never places an order" and to the backtest-gate
  requirement, but **only** for autopilot orders on the `ai` account, inside the fence below. The
  kill switch still applies, with no exception. `AGENTS.md` and `.claude/CLAUDE.md` are updated in
  the same commit that ships the autopilot.
- **Paper first.** The autopilot runs against a paper ledger for the `ai` account until the user
  flips it to live, starting with a small capital setting.
- F&O stays out of autopilot scope (NSE equity CNC/MIS only).

## 1. Account roles and routing

- `prefs.broker_roles: {"kite": "ai", "upstox": "mine"}`, validated (known brokers; at most one
  `ai`). Settings → Broker shows each connected broker with an "AI account / My account" control.
- `brokers/roles.py`: `async adapter_for(user_id, role, credentials) -> adapter` raises
  `RoleUnavailable(role, reason)` when unset, disconnected, or not ACTIVE.
- Replace both `get_active_broker_adapter` and `chat/actions._active_broker` call sites:
  - engine live routing and the autopilot → `adapter_for(..., "ai")`;
  - chat cards' live orders and new Upstox cards → `adapter_for(..., "mine")`.
- The portfolio, journal sync and analysis keep reading **every** connected broker; roles only
  label them.

## 2. Upstox: the AI proposes, the user confirms

New propose-only tools in `chat/actions.py`, each a card through the existing `confirm()` path. At
confirm time, each re-checks the market session, the role session, the kill switch, the position or
order still existing, and the per-trade cap.

- `propose_exit(symbol, quantity=None)`: sell all or part of a holding or position on `mine`.
- `propose_cancel_order(order_id)` and `propose_modify_order(order_id, price=None, quantity=None)`.
  These need `modify_order` in the protocol, implemented for Upstox (Kite later).
- `propose_stop_loss(symbol, trigger_price)`: a broker stop-loss trigger order where the Upstox
  API supports it, otherwise an SL-M order. It is refused if the trigger is above the last price
  for a long.

Live cards keep the second tap. `propose_order` gains `account: "mine"` as its default. It can never
target `ai`, because the autopilot owns that account.

## 3. Kite autopilot (fenced)

`backend/autopilot/` with its own settings in prefs:

| Setting | Default | Meaning |
|---|---|---|
| `autopilot_enabled` | false | master switch |
| `autopilot_live` | false | paper vs real orders on the `ai` account |
| `autopilot_capital` | ₹25,000 | the most the autopilot may have deployed at once |
| `autopilot_per_trade_cap` | ₹5,000 | notional per order |
| `autopilot_max_trades_per_day` | 5 | entries per day |
| `autopilot_daily_loss_limit` | ₹1,000 | trips the kill switch for the `ai` account for the day |
| `autopilot_universe` | Nifty 200 | allowed symbols, NSE equity only |

- **Sources:**
  - the factor portfolio's rebalance orders (backtested);
  - action cards the AI creates in chat for the `ai` account;
  - engine proposals.

  Each becomes an `AutopilotOrder` with a `source` and the AI's `reason`.
- **Fence** (`autopilot/fence.py`, a pure function, fully unit-tested). Every check runs before any
  order:
  - enabled;
  - market open;
  - the `ai` role ACTIVE (live) or the paper ledger (paper);
  - kill switch clear;
  - symbol in universe and NSE equity;
  - CNC or MIS only;
  - notional ≤ per-trade cap;
  - deployed + notional ≤ capital;
  - entries today < max;
  - not a duplicate of an open order.

  A refused order is logged with its reason, never retried silently.
- **Execution:** paper goes through `fill_on_paper` into an `ai`-tagged ledger; live goes through the
  `ai` adapter's `place_order`, then a status poll, as today's live path does.
- **Visibility:** every placed or refused order goes to `autopilot_log` and to Telegram ("🤖 AI
  bought 10 INFY on Kite: <reason>") with a 🛑 *Stop autopilot* button (callback
  `nt:autopilot:off`, the same callback path as cards). A Settings → AI section shows the switches,
  limits, today's activity and the log.
- **The kill switch** (`risk/kill_switch.py`) tracks the `ai` account's realized + unrealized P&L
  against `autopilot_daily_loss_limit`, and stops new autopilot entries for the day.

## 4. Analysis for both accounts

- **Portfolio:** `latest_snapshot` keeps one merged snapshot plus `by_broker` sub-totals. `/portfolio`
  and `/portfolio/refresh` accept `account=ai|mine|all`. Each view shows its own totals,
  concentration, plan and Nifty comparison.
- **Journal:** `GET /journal?account=` filters trips by the brokers in that role. Calendar,
  insights and the mirror (charges, trades/yr, vs Nifty) all follow the filter.
- **AI vs you:** `GET /journal/ai-vs-me`: per month, each account's net P&L, return on capital,
  charges, trade count and Nifty return. The scorecard sits on the Journal page and goes into the
  Friday Telegram note.
- **Chat:** `get_portfolio`, `get_journal` and `query_my_data` take `account` (default `all`), and
  the prompt is told which account is which. The page note tells the model that orders on `mine`
  are cards and that the `ai` account is the autopilot's.
- **Frontend:** an account switch (Both / AI · Kite / Mine · Upstox) on Portfolio and Journal,
  remembered per viewer.

## Setup the user does (documented on Settings → Broker)

- Kite Connect app (API key and secret), with redirect URL
  `https://neotrade.161.118.167.148.nip.io/...` (the existing Kite login route).
- Whitelist the server's static IP **161.118.167.148** with Zerodha and with Upstox (SEBI retail
  API rule, in force from 2026-04-01).
- Daily login on both: sessions expire each day. A 09:00 IST Telegram reminder fires if the `ai`
  session is not ACTIVE while the autopilot is enabled.

## Errors

- A missing or inactive role gives a clear refusal (chat card text, Telegram, 409 from APIs). There
  is never a fallback to the other account.
- A broker error while placing an order is logged, sent to Telegram, and the order is not retried
  automatically.
- A fence refusal is logged and counted in the daily summary, never silent.

## Testing

- `test_broker_roles.py`: validation, `adapter_for` refusals, no fallback across roles.
- `test_autopilot_fence.py`: every limit, exactly at the boundary and over it; kill switch;
  duplicates; market closed.
- `test_autopilot.py`: sources → fence → paper fill + log + Telegram; the 🛑 callback disables it;
  live uses only the `ai` adapter (a fake adapter asserts it is never the Upstox one).
- `test_chat_actions.py`: the new Upstox cards and their confirm-time re-checks; `propose_order`
  never targets `ai`.
- Portfolio and journal account filters, and the AI-vs-me scorecard.
- Frontend build.

## Build order (each a separately shippable step)

1. Roles and role-based routing (no behaviour change for a single broker).
2. Per-account analysis: portfolio and journal filters, AI-vs-me scorecard, account-aware tools.
3. Upstox cards: exit, cancel, modify, stop-loss (adds `modify_order`).
4. Kite autopilot, paper only: fence, sources, log, Telegram, stop button, settings.
5. Autopilot live switch, after a paper period the user reviews, with a small `autopilot_capital`.
