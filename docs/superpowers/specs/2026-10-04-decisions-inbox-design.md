# One Decisions inbox: paper and real money, every account

Date: 2026-10-04 · Status: design approved in chat ("Go"), awaiting spec review

Sub-project 3 of 4 (scanner → order ticket → **one decisions inbox** → research search page).

## Problem

Decisions are split and half-wired:
- Engine proposals (`suggestions`) live under AI → Practice → Decisions. They can be approved on
  paper; "Approve live" exists **only for option proposals** (`routers/suggestions.py`
  `approve_suggestion_live` returns 400 for equity).
- Pending chat and ticket cards (`chat_actions`, PROPOSED) have no page of their own; they only
  show as one-liners in Today → Needs you.
- What the AI account's autopilot did is on AI → Activity, away from everything else.

## Goal

One page, `/decisions`, where every decision the user can make sits together, each tagged with
its account, and any equity proposal can be approved **on paper or with real money on the
user's own account**.

## Non-goals

- No hand-off of a proposal to the AI account (declined). The AI section is read-only.
- No limit orders on approval (proposals execute at market, as today).
- No change to how proposals are generated, scored or expired.

## Backend

### 1. Equity approve-live (`backend/routers/suggestions.py` `approve_suggestion_live`)

Option proposals: unchanged. Equity proposals, in order:
1. PENDING check (existing), kill switch (existing).
2. `in_session(now)` else 409 `"The market is closed; live orders go only between 09:15 and
   15:30 IST on weekdays."`
3. Mine adapter: new dependency `get_mine_broker()` returning `async (user_id) -> adapter | None`
   via `adapter_for(user_id, "mine", get_credential_store(), db.redis)` (`RoleUnavailable` →
   None). None → 409 `"Connect your broker and set it as My account in Settings to approve with
   real money."` Never the `ai` role.
4. Cap: `mark × quantity` (mark via the injected `get_mark_price`) over `prefs.per_trade_cap` →
   409 `"₹{value} is over your per-trade cap of ₹{cap}."`
5. Claim `PENDING → SENDING` (existing pattern; concurrent second approve → 409).
6. `Order(order_type="MARKET", product="CNC" if mode == "LONGTERM" else "MIS",
   strategy_name=suggestion["strategy"], suggestion_id=id)` through `execute_live_order(order,
   ledger, adapter, LiveOrderStore(db), "approve", reason)`.
7. Settle exactly as options do: filled > 0 → EXECUTED (`venue="live"`); REJECTED/CANCELLED →
   back to PENDING with `"Broker {status} the order"`; else SENT `"Placed with your broker, not
   filled yet"`. A broker exception → PENDING with `"Broker refused: …"` and 502 (existing).

The route's docstring and the AGENTS.md line about approve-live are updated: equity approvals
now place real orders on the `mine` account only.

### 2. Chat approve cards (`backend/chat/actions.py`)

`_pending_suggestion(..., live=True)` drops `"Only option proposals can be approved live"`; the
card still needs the second tap and `_execute` calls the same route, so all checks above run at
confirm.

### 3. Pending cards: `GET /chat/actions/pending` (`backend/routers/chat_actions.py`)

Returns the user's `chat_actions` with `status == "PROPOSED"` and `expires_at > now`, newest
first, fields `id, kind, summary, venue, needs_second_tap, expires_at`. Confirm/cancel stay on
the existing routes.

## Frontend

### Route and navigation

- New `frontend/src/pages/Decisions.jsx` (from `Suggestions.jsx`) at `/decisions`, outside
  `PaperShell` (it is not practice-only). `Suggestions.jsx` is deleted.
- Redirects: `/ai/practice/decisions` and `/suggestions` → `/decisions`.
- Practice tabs (`PaperShell.jsx`): the Decisions tab links to `/decisions` (keeps its counter).
- Today → Needs you header gets `All decisions ›` → `/decisions`.

### Page layout

Account filter at top: **All · Paper · Mine · AI** (`Tabs`, local state; default All).

1. **Proposals** (shown for All, Paper, Mine): existing Long term / Intraday tabs, show-decided
   toggle and Scan now. Each pending equity or option card (`SuggestionRecord`) gets:
   - **Approve on paper** (existing `approve`);
   - **Approve with real money**: two taps, as option live approval already works
     ("Approve with real money" → "Send real order"). Disabled with the link `Connect your
     broker and set it as My account in Settings` (`/settings?tab=accounts`) when no
     `broker_roles` value is `"mine"`.
   `canGoLive` no longer requires `option_contract`.
2. **Waiting for you** (All, Paper, Mine; filtered by card `venue` — `paper` → Paper, `live` →
   Mine): pending cards from `GET /chat/actions/pending`, each with its summary, a Paper/Mine
   tag, time left, **Confirm** (second tap for Mine, server-enforced: `NEEDS_SECOND_TAP` →
   "Real money. Tap Confirm again") and **Cancel**. Hidden when empty.
3. **AI account today** (All, AI): read-only, the latest 10 rows of `GET
   /settings/autopilot/log` from today (IST) — time, action, symbol, quantity, reason for a
   refusal — and `See all on AI → Activity ›`. Empty: "The autopilot has not acted today."

Proposal cards show which account an approval would hit (`Paper` / `Your account`) on their
two buttons; nothing on this page can trade the AI account.

## Testing

`test_suggestions_router.py` (extend), fake Mine broker via `get_mine_broker` override:
- equity approve-live fills → EXECUTED, `venue == "live"`, the fake broker got a MARKET CNC
  order for a LONGTERM proposal (MIS for INTRADAY);
- not filled → SENT; broker REJECTED → PENDING with reason; broker raises → PENDING + 502;
- refused (409, nothing placed): market closed, over cap, kill switch tripped, no Mine broker;
- two concurrent approve-live calls place one order;
- option approve-live unchanged (existing tests stay green).

`test_chat_actions.py`: an equity approve card with `live=True` is proposed and, on confirm
with the second tap, reaches the route (fake Mine broker gets the order).

`test_chat_actions.py` (route): `GET /chat/actions/pending` returns only the caller's PROPOSED,
unexpired cards.

Frontend: `npm run build` + lint.
