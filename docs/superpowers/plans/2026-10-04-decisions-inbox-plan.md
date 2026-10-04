# Decisions Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `/decisions` page with proposals (approve on paper or with real money on Mine, equity included), pending chat/ticket cards, and a read-only AI-account section.

**Architecture:** `approve_suggestion_live` gains an equity branch on the `mine` adapter (session, cap, claim, MARKET via `execute_live_order`). Chat approve cards drop their options-only rule. `GET /chat/actions/pending` feeds the page. `Suggestions.jsx` becomes `Decisions.jsx` at `/decisions` with an account filter.

**Tech Stack:** FastAPI, Motor/mongomock_motor, pytest; React 19 + Vite.

**Spec:** `docs/superpowers/specs/2026-10-04-decisions-inbox-design.md`

## Global Constraints

- Real-money approval only ever on `adapter_for(user, "mine", ...)`; never `ai`.
- Equity approve-live check order: PENDING → kill switch → `in_session` → Mine adapter → cap (mark × qty) → claim PENDING→SENDING → MARKET order (CNC for LONGTERM, MIS for INTRADAY) → settle as options do.
- Refusal copy exactly as the spec. Option approve-live behaviour unchanged.
- Frontend check: `npm run build` + `npx eslint <changed files>`.

## Review Focus

1. **Approve-live double tap / concurrent approvals** → one broker order. Test in Task 1.
2. **Broker exception after the claim** → back to PENDING, 502, nothing booked. Test in Task 1.
3. **A chat/ticket card expires while the page is open** → Confirm returns the expiry refusal shown inline; list refresh drops it. Task 3 handles 409 detail.
4. **User without a `mine` role** → real-money button disabled with the Settings link; server still refuses (Task 1 test).
5. **Old links `/ai/practice/decisions`, `/suggestions`** → land on `/decisions`. Task 3.

---

### Task 1: Equity approve-live on the user's own account

**Files:** Modify `backend/routers/suggestions.py`, `backend/chat/actions.py` (`_pending_suggestion`), `AGENTS.md` (approve-live line). Test: `backend/tests/test_suggestions_router.py`, `backend/tests/test_chat_actions.py`.

**Interfaces:**
- Produces in `routers/suggestions.py`: `async def _mine_broker(user_id) -> adapter | None`, `def get_mine_broker()` (dependency returning it), `def _now() -> datetime` (UTC; test seam).

- [ ] **Step 1: Failing tests** (`_with_mine(client, broker)` overrides `get_mine_broker`; `monkeypatch.setattr(suggestions_router, "_now", lambda: OPEN)` with `OPEN = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)`)

```python
def test_equity_approve_live_places_a_market_order_on_mine(...)      # LONGTERM → EXECUTED, venue live, placed[0].order_type == "MARKET", product "CNC"
def test_intraday_equity_approve_live_is_mis(...)                   # mode INTRADAY → product "MIS"
def test_equity_approve_live_not_filled_is_sent(...)                # statuses ("OPEN",) → SENT
def test_equity_approve_live_rejected_goes_back_to_pending(...)     # ("REJECTED",) → PENDING, reason "Broker rejected the order"
@pytest.mark.parametrize("why", ["closed", "cap", "kill", "no_mine"])
def test_equity_approve_live_refusals_place_nothing(...)            # 409 each, broker.placed == [], status stays PENDING
def test_equity_approve_live_twice_places_one_order(...)            # second call 409, len(placed) == 1
```

Replace the existing `assert ... equity ... == 400` line in `test_approve_live_needs_an_option_a_broker_and_no_kill_switch` with the option-only assertions (that equity is no longer 400 is pinned by the tests above). Chat: `test_equity_approve_card_live_reaches_mine` — propose `approve` with `live=True` on an equity suggestion, confirm with second tap, the fake Mine broker (override `routes.get_mine_broker` via monkeypatching `suggestions_router._mine_broker`) receives the order.

- [ ] **Step 2: Run, verify the new tests fail** — `python3 -m pytest backend/tests/test_suggestions_router.py backend/tests/test_chat_actions.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement** the equity branch exactly in the Global Constraints order; `_execute`'s approve call passes `mine_broker=routes._mine_broker` (and `mark_price=_mark_price`) to the route function. Update the route docstring and the AGENTS.md safety line.

- [ ] **Step 4: Run the two files, then the full suite** — all PASS.

- [ ] **Step 5: Commit** `feat(decisions): approve an equity proposal with real money on your own account`

---

### Task 2: Pending cards endpoint

**Files:** Modify `backend/chat/actions.py` (`ChatActionStore.pending(user_id) -> list[dict]`), `backend/routers/chat_actions.py` (`GET /chat/actions/pending`, declared before `/{action_id}/...`). Test: `backend/tests/test_chat_actions.py`.

- [ ] **Step 1: Failing test** `test_pending_cards_are_the_callers_unexpired_proposals` — alice PROPOSED (fresh), alice PROPOSED (expired), alice CONFIRMED, bob PROPOSED → route returns only alice's fresh one, fields `id, kind, summary, venue, needs_second_tap, expires_at`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (`expires_at > _now()`, sort `created_at` desc, projection excludes `_id, user_id, params, message`).
- [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** `feat(decisions): list the user's pending chat and ticket cards`

---

### Task 3: The `/decisions` page

**Files:** Create `frontend/src/pages/Decisions.jsx` (from `Suggestions.jsx`, which is deleted); modify `frontend/src/App.jsx` (route + redirects), `frontend/src/components/paper/PaperShell.jsx` (tab path), `frontend/src/pages/Today.jsx` (`All decisions ›`), `frontend/src/components/suggestions/SuggestionRecord.jsx` (live for equity, labels, disabled state), `frontend/src/utils/api.js` (`chat.pending`).

- [ ] **Step 1:** Build the page per the spec's Page layout: account filter (All · Paper · Mine · AI), Proposals, Waiting for you (confirm/second tap/cancel, `detail` string-only errors, refresh after each action), AI account today (today's IST rows of `autopilotLog`, max 10).
- [ ] **Step 2:** `SuggestionRecord`: `canGoLive = Boolean(onApproveLive)`; buttons "Approve on paper" / "Approve with real money" → "Send real order"; prop `hasMine` disables real money with the Settings link.
- [ ] **Step 3:** Routes: `/decisions` → `gated(<Decisions />)`; `/ai/practice/decisions` and `/suggestions` → `<Moved to="/decisions" />`; PaperShell tab path `/decisions`; Today link.
- [ ] **Step 4:** `cd frontend && npm run build && npx eslint <changed files>` → build OK, 0 errors.
- [ ] **Step 5: Commit** `feat(decisions): one inbox at /decisions -- proposals, waiting cards, the AI account today`
