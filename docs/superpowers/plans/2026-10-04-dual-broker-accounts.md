# Two Broker Accounts (Kite AI autopilot, Upstox mine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each connected broker a role — Kite `ai` (fenced autopilot), Upstox `mine` (AI proposes, user confirms) — route every order by role, and show analysis per account.

**Architecture:** A role map in prefs plus `brokers/roles.py` replaces "first ACTIVE broker" routing. Upstox gains propose-only exit, cancel, modify and stop-loss cards on the existing confirm path. `backend/autopilot/` turns AI or engine orders for the `ai` account into fenced paper (later live) fills, with a log, Telegram notes and a stop button. The portfolio and journal take an `account` filter.

**Tech Stack:** FastAPI, Motor/MongoDB (`mongomock_motor` in tests), httpx (Upstox v2 REST), LangChain `StructuredTool`, React 19 + Vite.

**Spec:** `docs/superpowers/specs/2026-10-04-dual-broker-accounts-design.md`

## Global Constraints

- Roles: `"ai"` | `"mine"`, stored in `prefs.broker_roles` (dict broker → role); at most one `ai`; brokers from `brokers/registry.py:BROKERS`.
- No cross-role fallback, ever. A missing or inactive role → `RoleUnavailable` → refusal text or a 409.
- An AI-originated order may reach a broker without a user tap **only** via `backend/autopilot/` on the `ai` role, after `fence.check` passes.
- Autopilot defaults: `autopilot_enabled=False`, `autopilot_live=False`, `autopilot_capital=25000`, `autopilot_per_trade_cap=5000`, `autopilot_max_trades_per_day=5`, `autopilot_daily_loss_limit=1000`; universe = `backend/factor/nifty200.csv`; NSE equity CNC/MIS only; market hours (`engine/autorun.in_session`).
- Kill switch (`risk/kill_switch.py`) always applies; live cards keep their second tap.
- Every per-account record carries `user_id`; prompts only in `backend/prompts/*.md`.
- Tests: `python3 -m pytest -q -p no:cacheprovider` (3 known failures in `test_instrument_loader_kite_refresh.py` belong to another change); frontend `npm --prefix frontend run build`.
- Another agent works in this repo. Stage only this plan's files; pull before pushing; commits end with `[skip ci]` (session deploy mode: Direct).

## Review Focus

- User sets **both** brokers to `ai` → 422; one role per broker; switching Kite from `ai` to `mine` disables the autopilot. Test in Task 1.
- `ai` session expired at 09:15 with the autopilot on → orders refused with "Kite is not logged in", a Telegram reminder, no Upstox fallback. Test in Task 4.
- An autopilot order exactly at the per-trade cap or exactly filling capital → allowed; ₹1 over → refused. Test in Task 4.
- `propose_exit` for more shares than held, or a symbol not held → refused at propose and again at confirm (the position could have changed). Test in Task 3.
- A Telegram 🛑 tap after the autopilot is already off → "Autopilot is already off", no error. Test in Task 4.

---

### Task 1: Account roles and role-based routing

**Files:**
- Create: `backend/brokers/roles.py`
- Modify: `backend/prefs.py` (DEFAULTS `broker_roles: {}`), `backend/routers/settings.py` (`PreferencesPatch.broker_roles` + validator), `backend/routers/trading.py:315` (live routing → `ai`), `backend/chat/actions.py:55-59,178` (`_active_broker` → `mine`), `backend/routers/suggestions.py:181` (`_options_broker` → `mine`), `frontend/src/pages/Settings.jsx` (BrokerSheet role control)
- Test: `backend/tests/test_broker_roles.py`

**Interfaces:**
- Produces: `class RoleUnavailable(Exception)` with `.role` and `.reason`; `async def adapter_for(user_id: str, role: Literal["ai","mine"], credentials, redis=None) -> BrokerAdapter` (raises `RoleUnavailable` when no broker has the role, its credentials are missing, or its session is not ACTIVE); `def brokers_for(roles: dict, role: str) -> set[str]`; `def validate_roles(roles: dict) -> dict` (raises `ValueError`).

- [ ] **Step 1: Failing tests.**
  - `test_validate_roles_allows_one_ai_and_known_brokers`: `{"kite":"ai","upstox":"mine"}` ok; `{"kite":"ai","upstox":"ai"}` raises; `{"zerodha":"ai"}` raises; `{"kite":"boss"}` raises.
  - `test_adapter_for_returns_only_the_brokers_role_and_never_falls_back`: fake `get_broker_adapter` with kite ACTIVE and upstox ACTIVE; roles kite=ai → `adapter_for(...,"ai")` is the kite fake. With kite DISCONNECTED → raises `RoleUnavailable` with "kite" in the reason (not the upstox adapter).
  - `test_put_preferences_rejects_two_ai_accounts` (settings router client, as in `test_settings_router.py`) → 422.
  - `test_switching_kite_off_ai_disables_autopilot`: PUT `broker_roles={"kite":"mine"}` while `autopilot_enabled` is true → saved prefs have `autopilot_enabled` false.
- [ ] **Step 2:** Run `python3 -m pytest -q -p no:cacheprovider backend/tests/test_broker_roles.py` → FAIL (module missing).
- [ ] **Step 3:** Implement `roles.py`, the prefs default and the patch validator (the PUT handler sets `autopilot_enabled=False` when the new roles have no `ai`). Replace the three call sites. `routers/trading.py` live routing uses `adapter_for(user_id, "ai", ...)` and treats `RoleUnavailable` as "no live adapter" (paper fallback inside the engine stays as today). Chat order cards and option approvals use `"mine"`, and their refusal text names the role ("Your account (Upstox) is not logged in"). Keep `get_active_broker_adapter` only where it reads data (feeds), not orders.
- [ ] **Step 4:** In the Settings BrokerSheet, each connected broker row gets a two-option control "AI account / My account". It PUTs `broker_roles` and shows the 422 detail inline.
- [ ] **Step 5:** Run the new tests and the full suite → PASS (existing chat-actions and live tests updated to set `broker_roles`); `npm --prefix frontend run build` → built.
- [ ] **Step 6: Commit** `feat(brokers): account roles; orders route by role, never by fallback [skip ci]`.

### Task 2: Per-account analysis (backend)

**Files:**
- Modify: `backend/routers/journal.py` (`account` query on `GET /journal`, new `GET /journal/ai-vs-me`), `backend/routers/portfolio.py` + `backend/portfolio/service.py` (`account` filter), `backend/chat/tools.py` (`account` arg on `get_portfolio`, `get_journal`), `backend/scheduler.py` (`_weekly_mirrors` adds the AI-vs-me line), `backend/prompts/chat.md` (which account is which)
- Test: `backend/tests/test_account_analysis.py`

**Interfaces:**
- Consumes: `brokers_for(roles, role)` (Task 1); `mirror.costs`, `mirror.benchmark` (`backend/journal/mirror.py`).
- Produces: `def filter_trades(trades: list[dict], brokers: set[str] | None) -> list[dict]` in `backend/journal/accounts.py`; `def scorecard_for(snapshot: dict, brokers: set[str]) -> dict` in `backend/portfolio/service.py` (re-runs `build_scorecard` on `raw_holdings` of those brokers, no AI review); `def ai_vs_me(trades, roles, capital_by_role, nifty) -> list[dict]` (per month: `{"month", "ai": {...}, "mine": {...}, "nifty_return"}`, with net_pnl, return, charges, fills per side).

- [ ] **Step 1: Failing tests.**
  - `test_journal_account_filter`: trades from kite and upstox; `GET /journal?account=mine` → only upstox round trips, and the mirror counts only those fills.
  - `test_portfolio_account_view`: a snapshot with holdings from both brokers → `scorecard_for(snap, {"upstox"})["totals"]` covers only upstox holdings.
  - `test_ai_vs_me_by_month`: two months of fills on each account → each month row has both sides' net P&L (after estimated charges) and `nifty_return`.
  - `test_tools_take_account`: `get_journal(account="ai")` output has only kite trips.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `account` ∈ `all|ai|mine` (default `all`); an unset role → empty result plus `"note": "No broker is set as <role>"`. Capital for the AI side = `autopilot_capital`, for mine = `account_size`. In `chat.md`: "The trader has an AI account (the autopilot trades it) and their own account (you only propose cards there); answer per account when asked."
- [ ] **Step 4:** Run the new tests and the full suite → PASS.
- [ ] **Step 5: Commit** `feat(analysis): portfolio, journal and chat per account; AI vs you by month [skip ci]`.

### Task 3: Upstox cards — exit, cancel, modify, stop-loss

**Files:**
- Modify: `backend/core/models.py` (`Order.order_type` adds `"SL-M"`; `trigger_price: Optional[float] = None`), `backend/brokers/protocol.py` (`modify_order`), `backend/brokers/upstox.py` (`modify_order`, SL-M in `place_order`, `get_orders`), `backend/chat/actions.py` (4 tools + confirm branches), `backend/agent.py` labels if present (`chat/agent.py` `TOOL_LABELS`)
- Test: `backend/tests/test_upstox_cards.py`

**Interfaces:**
- Consumes: `adapter_for(user_id, "mine", credentials)` (Task 1).
- Produces: protocol `async def modify_order(self, broker_order_id: str, quantity: Optional[int] = None, price: Optional[float] = None, trigger_price: Optional[float] = None) -> None` (Upstox: `PUT https://api.upstox.com/v2/order/modify`); `async def get_orders(self) -> list[dict]` (Upstox: `GET https://api.upstox.com/v2/order/retrieve-all`, each `{order_id, symbol, side, quantity, price, trigger_price, status}`). Tools: `propose_exit(symbol: str, quantity: Optional[int] = None)`, `propose_cancel_order(order_id: str)`, `propose_modify_order(order_id: str, price: Optional[float] = None, quantity: Optional[int] = None)`, `propose_stop_loss(symbol: str, trigger_price: float)`. Card kinds: `exit`, `cancel_order`, `modify_order`, `stop_loss`, all `venue="live"` with `second_tap=True`.

- [ ] **Step 1: Failing tests** (fake Upstox adapter injected via `adapter_for` monkeypatch).
  - `test_exit_card_checks_holding_at_propose_and_confirm`: holding 10 INFY; `propose_exit("INFY", 15)` refused ("you hold 10"); `propose_exit("INFY")` gives a card for 10. The position is sold to 0 before confirm → confirm raises `ActionRefused`.
  - `test_cancel_and_modify_reach_only_the_mine_adapter`: the fake records calls; confirm cancel → `cancel_order("O1")` on the upstox fake; the kite fake is never called.
  - `test_stop_loss_refuses_a_trigger_above_the_price_for_a_long`: last price 1500, trigger 1600 → refused; trigger 1400 → card; confirm → the upstox fake receives `Order(order_type="SL-M", trigger_price=1400, side=SELL)`.
  - `test_upstox_place_order_sends_sl_m_fields` (httpx mock): body has `order_type="SL-M"`, `trigger_price=1400`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Confirm re-checks: market session, the `mine` role ACTIVE, kill switch, holding/order still present, per-trade cap. `propose_order` gains `account: Literal["mine","ai"] = "mine"`. With `"ai"` it hands the order to the autopilot (Task 4) and returns its result text, or "The autopilot is off" when disabled.
- [ ] **Step 4:** Run → PASS; full suite.
- [ ] **Step 5: Commit** `feat(upstox): AI-proposed exit, cancel, modify and stop-loss cards [skip ci]`.

### Task 4: Kite autopilot on paper — fence, execution, log, Telegram stop

**Files:**
- Create: `backend/autopilot/__init__.py`, `backend/autopilot/fence.py`, `backend/autopilot/service.py`, `frontend/src/components/settings/AutopilotSheet.jsx`
- Modify: `backend/prefs.py` + `routers/settings.py` (the autopilot settings above), `backend/guardrails/telegram_bot.py` (`nt:autopilot:off` callback), `backend/engine/autorun.py` (09:00 reminder; route `factor/paper.rebalance` orders through the autopilot when it is enabled), `backend/routers/settings.py` (`GET /settings/autopilot/log`), `frontend/src/pages/Settings.jsx` (AI tab mounts AutopilotSheet)
- Test: `backend/tests/test_autopilot.py`

**Interfaces:**
- Consumes: `adapter_for(..., "ai")` (Task 1); `factor.paper` rebalance orders; `notify` (`suggestions/notify.py`); `fill_on_paper` (`suggestions/service.py`).
- Produces: `@dataclass AutopilotOrder(symbol: str, side: Side, quantity: int, product: Literal["CNC","MIS"], source: Literal["chat","engine","factor"], reason: str)`; `def check(order: AutopilotOrder, price: float, state: FenceState, prefs: dict, now: datetime) -> Optional[str]` (None = allowed, else a refusal reason), where `FenceState(deployed: float, entries_today: int, open_symbols: set[str], kill_tripped: bool, session_ok: bool)`; `async def submit(db, redis, user_id: str, order: AutopilotOrder, now=None) -> dict` (`{"status": "FILLED"|"REFUSED", "reason"?, "price"?}`, logs to `autopilot_log`, sends a Telegram note with the 🛑 button); `async def disable(db, user_id) -> bool` (False if already off).

- [ ] **Step 1: Failing tests.**
  - `test_fence_limits`, parametrised: notional == per-trade cap → allowed; cap+1 → "per-trade cap"; deployed+notional == capital → allowed, +1 → "capital"; entries_today == max → "trades today"; symbol outside Nifty 200 → "universe"; product NRML → "NSE equity only"; kill_tripped → "loss limit"; session closed → "market closed"; duplicate open symbol BUY → "already holding". Exits (SELL of a held symbol) bypass the capital and entry counts.
  - `test_submit_paper_fills_logs_and_notifies`: enabled, paper → `paper_trades` row with strategy `autopilot:chat`, an `autopilot_log` row, and a notify text starting "🤖 AI bought".
  - `test_submit_refusal_is_logged_not_retried`: over the cap → REFUSED, logged, notified once, no trade.
  - `test_disabled_autopilot_refuses_everything`.
  - `test_ai_session_missing_in_live_mode_refuses_without_fallback`: `autopilot_live=True`, `adapter_for` raises → REFUSED "Kite is not logged in"; the upstox fake is never touched.
  - `test_stop_button_disables_once`: callback `nt:autopilot:off` → disabled, card edited "🛑 Autopilot stopped"; a second tap → "Autopilot is already off".
  - `test_daily_loss_trips_the_kill_switch`: ai-ledger day P&L −1001 → subsequent submits refused "loss limit".
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Paper ledger = `LedgerStore(db, user_id)` with `strategy_name=f"autopilot:{source}"`. `deployed` = open paper positions with an `autopilot:` strategy, at mark. The kill-switch check compares the day's realized + unrealized P&L of `autopilot:` trades with `autopilot_daily_loss_limit` and calls `KillSwitchStore.trip`. 09:00 IST reminder: autopilot enabled and the `ai` role not ACTIVE → notify once per day. The AutopilotSheet shows the switches and limits (PUT preferences), today's count, deployed vs capital, and the last 20 log rows.
- [ ] **Step 4:** Run the new tests and the full suite → PASS; frontend build.
- [ ] **Step 5: Commit** `feat(autopilot): fenced AI autopilot on the Kite account, paper first [skip ci]`.

### Task 5: Autopilot live switch, docs and deploy

**Files:**
- Modify: `backend/autopilot/service.py` (live path), `AGENTS.md`, `.claude/CLAUDE.md` (invariant exception), `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `frontend/src/components/settings/AutopilotSheet.jsx` (live toggle with a typed confirmation "LIVE")
- Test: `backend/tests/test_autopilot.py` (live cases)

- [ ] **Step 1: Failing test** `test_live_mode_places_on_the_ai_adapter_only`: `autopilot_live=True`; fake kite adapter ACTIVE → `place_order` called once with an `Order(product="CNC", strategy_name="autopilot:chat")` and the status polled; the fake upstox adapter is never called; the log records the broker order id.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the live path: `adapter_for(user_id, "ai")` → `place_order` → `get_order_status` poll (as `execute_option_suggestion_live` does), with fills booked as live. In `AGENTS.md` and `.claude/CLAUDE.md`, the invariant text gains: "Exception (user-approved 2026-10-04): `backend/autopilot/` may place orders without a user tap on the `ai` role only, after `autopilot/fence.check` passes; the kill switch still applies." Update ARCHITECTURE (the roles + autopilot paragraph) and ROADMAP (a dated entry). The live toggle in the UI requires typing LIVE.
- [ ] **Step 4:** Full suite → PASS; build; deploy (`git push`; `docker compose build backend && up -d backend` in `/home/ubuntu/deploys/NeoTrade`); `/` → 200 within 30s.
- [ ] **Step 5: Commit** `feat(autopilot): live mode on the AI account; document the invariant exception [skip ci]`.
