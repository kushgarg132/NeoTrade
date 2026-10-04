# UI restructure around the user's day — design

Date: 2026-10-05. Status: approved in chat ("Do it"), awaiting spec review.

## Goal

Restructure NeoTrade around what a trader needs at each moment of the day. There are now three
kinds of money: the user's own account (`mine`, Upstox), the AI account (`ai`, Kite autopilot),
and practice (paper). Today the navigation hides that split, and "what needs me now" has no
home.

Success:
- One glance at **Today** answers "can it trade, what needs me, where am I".
- Every number says whose money it is.
- Setup is a checklist.
- No feature is lost; old links still work.

## Journeys this must serve

| Moment | Question | Answered by |
|---|---|---|
| 09:00, phone | Can it trade today? Anything waiting? | Today: status strip + Needs you |
| In session | Where am I? Anything I should stop? | Today: P&L Mine/AI, AI activity + Stop |
| After close | What did I do wrong? What did charges eat? | Mine → Habits |
| Weekly | Portfolio OK? Is the AI beating me and the Nifty? | Mine → Holdings; AI → Overview (AI vs you) |
| Curious | What about this stock? | Research |
| Once | Connect, set roles, set limits | Today's setup checklist → More |

## Information architecture

Phone bottom bar and desktop index both show **Today · Mine · AI · Research · More**. The chat
margin note stays on every page.

| Section | Route(s) | Content (reuse first) |
|---|---|---|
| **Today** | `/` | New `Today.jsx`: status strip, setup checklist (until done), Needs you, P&L Mine/AI, AI activity, index cards (existing `IndexCard`/`Market`, compact) |
| **Mine** | `/mine/holdings`, `/mine/trades`, `/mine/habits` | Holdings = `MyPortfolio` (locked to `account=mine`); Trades = `Journal` calendar + trades tabs (`account=mine`); Habits = Journal patterns + charges mirror |
| **AI** | `/ai`, `/ai/activity`, `/ai/practice/*`, `/ai/limits` | Overview (new): autopilot state, capital used, P&L vs Nifty, AI vs you; Activity: autopilot log + positions; Practice: the existing `/paper/*` pages; Limits: `AutopilotSheet` |
| **Research** | `/research`, `/research/scanner`, `/research/options` | Search (`SmartSearch`) + `Watchlist`; `ScannerPage`; `OptionChain` |
| **More** | `/settings?tab=accounts\|safety\|ai\|about` | Accounts = `BrokerSheet` (+ roles); Safety = `GuardrailsSheet` + daily loss (moved from Paper settings' read-only copy) ; AI = `ModelSheet` + Profile link + Telegram; About = Architecture (`/system` moves here) |

**Redirects (old links keep working):**
- `/portfolio` → `/mine/holdings`
- `/journal` → `/mine/trades`
- `/watchlist` → `/research`
- `/scanner` → `/research/scanner`
- `/options` → `/research/options`
- `/paper` → `/ai/practice`
- `/paper/*` → `/ai/practice/*`
- `/system` → `/settings?tab=about`
- `/suggestions`, `/trading` → their new practice paths.

**Section tabs:** a shared `SectionTabs` component sits at the top of each page in a section, and
each tab is its own route. Pages are not embedded inside each other, so no page renders a
second `<Layout>`.

The Mine pages drop the Both/AI/Mine switch and pass `account=mine`. The switch survives only on
**AI → Overview**, as the AI vs you comparison.

## Today (phone wireframe)

```
┌──────────────────────────────┐
│ ● Market open · 11:42 IST    │  status strip (sticky)
│ Upstox ✓  Kite·AI ✗ log in › │  (each chip tappable)
│ ▲ LIVE armed · 2 strategies  │  only when true, loss-red
├──────────────────────────────┤
│ Set up NeoTrade        3/6 ▸ │  only until complete
├──────────────────────────────┤
│ NEEDS YOU (2)                │
│ ○ Approve SJVN · expires 2d ›│
│ ○ Log in to Kite (AI)       ›│
│   — or —  "You're clear."    │
├──────────────────────────────┤
│ TODAY        Mine     AI     │
│            +₹1,240  −₹310    │  each → its section
├──────────────────────────────┤
│ AI ACTIVITY        [🛑 Stop] │
│ 🤖 bought 3 INFY · 10:05     │
│ ✖ refused TCS · per-trade cap│
├──────────────────────────────┤
│ NIFTY 22,422 −0.4%  BANK …   │
└──────────────────────────────┘
```

## AI → Overview (phone wireframe)

```
┌──────────────────────────────┐
│ Overview  Activity  Practice │  SectionTabs
│ Limits                       │
├──────────────────────────────┤
│ Autopilot  ON · paper        │
│ ₹12,400 of ₹25,000 deployed  │  bar
│ Today −₹310 · Month +₹2,100  │
├──────────────────────────────┤
│ AI vs YOU (month)            │
│ AI +₹2,100  You −₹640        │
│ Nifty −1.2%                  │
└──────────────────────────────┘
```

## Backend: `GET /today`

`backend/routers/today.py`, auth required. One call drives the strip, the checklist and the Needs
you list. Each part fails independently (a failed part reports `null` plus `errors[part]`).

```json
{
  "market": {"open": true, "as_of": "...", "next_open": "..."},
  "accounts": {"mine": {"broker": "upstox", "state": "ACTIVE"}, "ai": {"broker": "kite", "state": "NEEDS_LOGIN"}},
  "live_armed": {"autopilot": false, "strategies": ["..."]},
  "kill_switch": {"tripped": false, "reason": null},
  "needs_you": [{"kind": "proposal|card|login|guardrail", "title": "...", "detail": "...", "expires_at": "...", "link": "/ai/practice/decisions"}],
  "pnl_today": {"mine": 1240.0, "ai": -310.0},
  "ai_activity": [/* last 5 autopilot_log rows */],
  "setup": {"done": 3, "total": 6, "steps": [{"id": "connect_mine", "label": "...", "done": true, "link": "..."}]}
}
```

- **accounts:** from `prefs.broker_roles` + `get_broker_adapter(...).state()` per role broker (no order calls).
- **live_armed:** autopilot when `autopilot_enabled and autopilot_live`; strategies = `prefs.live_strategies` ∩ gate-eligible, as Engine settings already computes.
- **needs_you, in this order:**
  - login (a role's broker not ACTIVE);
  - kill switch;
  - pending proposals, soonest expiry first (max 5);
  - PROPOSED chat cards;
  - today's guardrail alerts.
- **pnl_today:**
  - mine = closed round trips today from the journal (net is not available intraday; label it "gross");
  - ai = today's realized + unrealized P&L of the autopilot ledger (`<uid>:autopilot`).
- **setup steps:**
  - `connect_mine` and `connect_ai`: a broker with that role has credentials;
  - `roles`: both roles set;
  - `daily_loss`: `daily_loss_limit` > 0 and guardrails on;
  - `telegram`: the user has a linked chat;
  - `profile`: at least 3 profile fields set.

## Visual language

- **Whose money:** Mine = ink, AI = violet (a new `--ai` token, defined in both themes), Practice = dashed rule. Every P&L figure carries its badge (`Mine` / `AI` / `Paper`).
- **Freshness:** live numbers show "updated Ns ago" from the socket; when the market is closed: "Market closed · as of 15:30".
- **Empty Needs you:** "You're clear." in display type, not an empty box.

## Out of scope

- No new data or features beyond `GET /today` and the AI Overview card. Everything else is moved, not rebuilt.
- No change to the chat, Telegram or trading logic.

## Errors

- A part of `/today` that fails shows an inline "couldn't load" with a retry; the page still renders.
- Every unknown old route still reaches NotFound.

## Testing

- `test_today.py`, against a mock DB:
  - each part: login needed, kill switch, proposals ordered by expiry, setup counts, pnl split by ledger;
  - a failing part degrades to `null` + `errors`.
- Frontend: `npm run build`; a manual pass of every redirect; phone-width check of Today and the bottom bar.
