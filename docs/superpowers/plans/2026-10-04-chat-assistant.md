# Chat Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The margin-note chat answers from the signed-in user's own data and proposes actions (including ad-hoc orders) that run only after a Confirm tap.

**Architecture:** New `backend/chat/` package: a per-message day snapshot in the system prompt, read tools and propose-only action tools bound to `user_id` by closure, and a `chat_actions` store whose confirm endpoint re-runs every check and executes through the app's existing code. The WS chat stream gains an `action` event; the widget renders cards and page-aware suggested questions.

**Tech Stack:** FastAPI, Motor/Mongo, Redis, LangChain/LangGraph `create_react_agent` over OmniRoute, React 19.

**Spec:** `docs/superpowers/specs/2026-10-04-chat-assistant-design.md`

## Global Constraints

- Every read and write is scoped by the caller's `user_id`; no tool takes a user id argument.
- Action tools never execute; only `POST /chat/actions/{id}/confirm` does, after re-checking from the database.
- `chat_actions` TTL: 5 minutes. Statuses: `PROPOSED|CONFIRMED|CANCELLED|EXPIRED|FAILED`.
- Settings whitelist: `daily_loss_limit, per_trade_cap, max_trades_per_day, cooldown_after_losses, cooldown_minutes, auto_paper_intraday, guardrails_enabled`.
- Ad-hoc orders: NSE equity, MARKET, whole quantity > 0, notional at a fresh mark ≤ `per_trade_cap`, `product` CNC or MIS; live additionally needs an ACTIVE broker, market in session (09:15–15:30 IST weekdays), kill switch not tripped today, and a second tap.
- Chat orders carry `strategy_name="chat"`; the user's message is stored on the `chat_actions` record and as `reason` on the `live_orders` record.
- Every LLM prompt lives in `backend/prompts/*.md`; `test_prompts.py` covers it.
- Backend tests: `docker run --rm -v $PWD:/app -w /app --entrypoint sh neotrade-backend -c "python -m pytest -q"` from the repo root. Frontend: `npx eslint src --quiet && npx vite build`.

## Review Focus

- Model invents a `suggestion_id` that is another user's or does not exist → proposal refused with "No such pending proposal" (test in Task 4).
- Confirm tapped twice quickly → second returns 409, one execution only (test in Task 4).
- Live order with `second_tap` false → nothing placed, status back to PROPOSED (test in Task 4).
- Quantity given as `10.5` or `0` or a symbol not on NSE → proposal refused with a reason (test in Task 4).
- Snapshot section raising (e.g. no portfolio yet) → snapshot still renders with that section marked unavailable (test in Task 2).

---

### Task 1: Shared execution for chat orders

**Files:**
- Modify: `backend/suggestions/service.py`, `backend/engine/execution/live_order_store.py`
- Test: `backend/tests/test_live_option_orders.py` (must keep passing), `backend/tests/test_chat_orders.py` (new)

**Interfaces:**
- Produces: `execute_suggestion(suggestion, ledger, price, now=None, strategy_name: str | None = None) -> Order`; `execute_live_order(order: Order, ledger, adapter, orders: LiveOrderStore, strategy_name: str = "", reason: str | None = None) -> tuple[Order, str, float]` (place, record, poll `LIVE_FILL_CHECKS`, book live fill); `LiveOrderStore.record_submitted(..., reason: str | None = None)`. `execute_option_suggestion_live` builds its Order and delegates to `execute_live_order`.

- [ ] Test `test_paper_chat_order_is_attributed_to_chat`: `execute_suggestion({"symbol":"INFY","side":"BUY","quantity":10,"mode":"LONGTERM"}, ledger, 1500.0, strategy_name="chat")` → the trade from `ledger.get_trades()` has `strategy == "chat"` and the order `product == "CNC"`.
- [ ] Test `test_live_equity_order_books_the_broker_fill`: fake adapter (`place_order` → `"B1"`, `get_order_status` → FILLED 10 @ 1501.0); `execute_live_order(Order(... product="CNC", strategy_name="chat"), ledger, adapter, LiveOrderStore(db), "chat", "buy 10 infy")` → returns status `FILLED`, filled 10; ledger fill venue `live` at 1501.0; `live_orders` doc has `reason == "buy 10 infy"` and `strategy_name == "chat"`.
- [ ] Run, see both fail. Implement. Run full suite, all pass. Commit `refactor(execution): share the live order path; attribute chat orders`.

### Task 2: Prompt and day snapshot

**Files:**
- Create: `backend/prompts/chat.md`, `backend/chat/__init__.py`, `backend/chat/context.py`
- Modify: `backend/tests/test_prompts.py` (add `"chat": {"snapshot": "...", "page": "/portfolio"}`)
- Test: `backend/tests/test_chat_context.py`

**Interfaces:**
- Produces: `async build_snapshot(db, redis, user_id: str, now: datetime | None = None) -> dict` with keys `market, portfolio, broker, decisions, paper, limits`, each a dict with `as_of` or `{"unavailable": "<reason>"}`; `format_snapshot(snapshot: dict) -> str` (compact lines for the prompt); `plan_names(plan: str | None, heading: str) -> list[str]` (bold names opening each bullet under `### <heading>`; same rule as the frontend's PortfolioGlance).
- `prompts/chat.md` placeholders: `{{snapshot}}`, `{{page}}`. System front matter carries the rules listed in the spec's `prompts/chat.md` section verbatim in meaning.

- [ ] Test `test_snapshot_is_scoped_to_the_user`: alice and bob each have a pending suggestion and a `user_prefs` doc; `build_snapshot(db, None, "alice")["decisions"]["pending"] == 1` and its top names contain only alice's symbol; `limits.daily_loss_limit` is alice's.
- [ ] Test `test_snapshot_marks_a_failing_section_unavailable`: monkeypatch `context.latest_snapshot` to raise → `snap["portfolio"] == {"unavailable": ...}` and other sections present.
- [ ] Test `test_plan_names_reads_bold_bullets`: plan `"### Sell or trim\n- **WIPRO**: x\n- **BDL** (y): z\n### Add\n- **HFCL** (Score 0.74): a"` → `plan_names(p, "sell") == ["WIPRO", "BDL"]`, `plan_names(p, "add") == ["HFCL"]`.
- [ ] Run, fail, implement (sources per the spec's snapshot table: `portfolio.service.latest_snapshot`, `JournalStore.list_trades` → `build_round_trips` → `daily_pnl`, `SuggestionStore.list(status="PENDING")`, `RunStore.list_active`, `KillSwitchStore.is_tripped`, `PrefsStore.get`, `GuardrailStore.events_for`, `engine.autorun.in_session`), pass, commit `feat(chat): system prompt and per-user day snapshot`.

### Task 3: Read tools

**Files:**
- Create: `backend/chat/tools.py`
- Test: `backend/tests/test_chat_tools.py`

**Interfaces:**
- Consumes: Task 2 `plan_names`.
- Produces: `read_tools(db, redis, user_id: str) -> list[BaseTool]` named `get_portfolio(symbol: str | None)`, `get_journal(period: Literal["today","week","month","all"]="month", symbol: str | None)`, `get_paper()`, `get_decisions(status: Literal["pending","decided"]="pending", symbol: str | None)`, `get_limits()`, `explain_index(ticker: str)`, plus the four existing tools from `backend/agents/tools.py`. Each returns a compact string (JSON or lines), never `_id`, trimmed (≤40 holdings, ≤30 round trips, ≤20 proposals).

- [ ] Test `test_read_tools_only_see_the_callers_data`: two users with suggestions, journal trades and portfolio snapshots; invoke each user-data tool for alice via `tool.ainvoke({...})`; bob's symbols never appear.
- [ ] Test `test_get_decisions_lists_ids_terms_and_score`: output for a pending suggestion contains its `id`, symbol, entry, stop, target and `score.final`.
- [ ] Run, fail, implement, pass, commit `feat(chat): read tools over the user's own data`.

### Task 4: Actions — propose, confirm, cancel

**Files:**
- Create: `backend/chat/actions.py`, `backend/routers/chat_actions.py`
- Modify: `backend/server.py` (include router under `/api/v1`, `ensure_indexes` at startup)
- Test: `backend/tests/test_chat_actions.py`

**Interfaces:**
- Consumes: Task 1 `execute_suggestion`, `execute_live_order`; existing `routers.suggestions.approve_suggestion` / `approve_suggestion_live` / `reject_suggestion` (called as functions with explicit deps), `routers.trading.launch_run`, `stop_background_run`, `RunStore`, `PrefsStore.update`, `KillSwitchStore.is_tripped`, `get_active_broker_adapter`, `InstrumentMaster.get("NSE", symbol)`, `routers.suggestions._live_mark_price`.
- Produces: `ChatActionStore(db)` with `ensure_indexes`, `propose(user_id, kind, params, summary, venue, needs_second_tap, message) -> dict card`, `get`, `claim(user_id, id, now) -> dict | None` (atomic PROPOSED→CONFIRMED, unexpired), `release`, `finish(id, status, result)`, `cancel`; `action_tools(db, redis, user_id, message) -> list[BaseTool]`: `propose_approve(suggestion_id, live=False)`, `propose_decline(suggestion_id, reason=None)`, `propose_paper_run(action: Literal["start","stop"])`, `propose_setting(name, value)`, `propose_order(symbol, side: Literal["BUY","SELL"], quantity: int, product: Literal["CNC","MIS"]="CNC", venue: Literal["paper","live"]="paper")`. Each returns `ACTION_CARD:` + card JSON on success or a plain refusal sentence. `async confirm(db, redis, credentials, user, action_id, second_tap) -> dict` raising `ActionRefused(reason)`. Routes: `POST /chat/actions/{id}/confirm` body `{second_tap: bool=false}` → 200 `{status, result}` or 409 `{detail}`; `POST /chat/actions/{id}/cancel`.

- [ ] Tests (fake broker adapter, mongomock, monkeypatched mark price and session clock):
  - `test_proposing_changes_nothing` — each kind proposed: no suggestion decided, prefs unchanged, no order, no run.
  - `test_propose_refuses_unknown_or_others_suggestion` — bob's id → refusal string, no record.
  - `test_propose_order_refuses_bad_input` — quantity 0, symbol not in master, notional over `per_trade_cap` → refusal; no record.
  - `test_confirm_runs_once` — paper order confirmed → one ledger trade with `strategy=="chat"`; second confirm → `ActionRefused`.
  - `test_confirm_refuses_expired_and_other_users` — expired → refused, record `EXPIRED`; bob confirming alice's id → refused.
  - `test_live_order_needs_second_tap` — first confirm returns `{status:"NEEDS_SECOND_TAP"}`, broker not called, record back to `PROPOSED`; with `second_tap=True` → placed.
  - `test_live_order_rechecks_at_confirm` — kill switch tripped after proposal → refused; market closed → refused; no active broker → refused.
  - `test_setting_change_is_whitelisted` — `propose_setting("account_size", 1)` refused; `daily_loss_limit` 5000 confirmed → prefs updated.
  - `test_confirm_route_maps_refusal_to_409`.
- [ ] Run, fail, implement, pass, commit `feat(chat): confirmable actions with server-side re-checks`.

### Task 5: Agent and streaming

**Files:**
- Create: `backend/chat/agent.py`
- Modify: `backend/ws/routes.py` (`_stream_chat(connection, message, history, req_id, context)`), delete `backend/components/chat/agent.py` and repoint `backend/routers/chat.py` to the new agent (or remove its route if it has no caller — check `grep -rn "chat/message" frontend/src`)
- Test: `backend/tests/test_chat_agent.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: `async stream_chat(db, redis, user_id, message, history, context: dict) -> AsyncIterator[dict]` yielding `{"type": "thinking"|"content"|"action", "data": str | dict}`; `action` when an action tool's output starts with `ACTION_CARD:` (data = parsed card). WS frames: `content`/`thinking` keep `{"text": ...}`; `action` sends the card dict.

- [ ] Test `test_stream_turns_an_action_tool_result_into_an_action_event`: monkeypatch `create_react_agent` with a fake whose `astream_events` yields an `on_tool_end` with output `ACTION_CARD:{"id":"a1",...}` then a content chunk → events include `{"type":"action","data":{"id":"a1",...}}` then content.
- [ ] Test `test_system_prompt_carries_snapshot_and_page`: capture the messages passed to the fake agent; first is a SystemMessage containing the snapshot text and `/portfolio`.
- [ ] Run, fail, implement (tools = `read_tools + action_tools(..., message)`; system prompt from `render("chat", snapshot=format_snapshot(...), page=...)`), pass full suite, commit `feat(chat): user-aware agent with action events`.

### Task 6: Widget — page context, action cards, suggested questions

**Files:**
- Modify: `frontend/src/components/ChatWidget.jsx`, `frontend/src/utils/api.js` (`chat.confirm(id)`, `chat.cancel(id)`)

**Interfaces:**
- Consumes: Task 5 WS events; Task 4 routes.

- [ ] Send `context: { page: location.pathname, symbol }` with each `stream.request('chat', ...)` (symbol from `location.state?.symbol` when present).
- [ ] Render `action` events as a card inside the thread: summary, venue tag (live in `--loss` ink), Confirm / Cancel; live orders show the second-tap prompt ("Real money: … Tap again to send.") exactly like `SuggestionRecord`; result or 409 detail prints in the card; card disables after a final state.
- [ ] Suggested-question chips above the input when the thread is empty, per page: `/` "How am I doing today?", "Anything waiting for me?"; `/portfolio` "What should I trim?", "Explain my biggest risk"; `/journal` "How did I do this month?", "What's my costliest habit?"; `/paper*` "Is the engine running?", "Which proposal is strongest?"; `/settings` "What are my limits?". Tap sends it.
- [ ] `npx eslint src --quiet && npx vite build` clean; commit `feat(frontend): chat knows the page, shows action cards and suggested questions`.

### Task 7: Docs and real-account verification

**Files:**
- Modify: `PRODUCT.md` (the "never places a trade the user cannot reconstruct" rule gains: "or, for an order placed from chat, the user's own message and their confirming tap"; Surfaces gains the chat), `docs/ARCHITECTURE.md` (§1.8 replaces the ChatAgent mention with `backend/chat/`), `docs/ROADMAP.md` (dated entry), `frontend/src/pages/SystemArchitecturePage.jsx` (OmniRoute part mentions the chat's tools and confirm cards).

- [ ] Push; after deploy, on the real account ask: "How's my portfolio today?", "Why is WIPRO a sell?", "How did I do this month?", "Is the engine running?", "Explain the SJVN proposal", "What's my daily loss limit?" — each answered from own data.
- [ ] Propose and Cancel each action kind; confirm one paper order and one setting change (then revert it). Do not confirm a live order.
- [ ] Commit docs `docs: chat assistant`.
