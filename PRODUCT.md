# NeoTrade — product truth

> What this product is and who it serves. For how it is built, see
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); for what gets built next, see
> [`docs/ROADMAP.md`](docs/ROADMAP.md).

## What it is

**The discipline layer on top of your broker**, for traders in **Indian equities and F&O**.
Each user connects their own broker account (Zerodha Kite, Upstox, or Angel One). NeoTrade
journals their real trades automatically, shows the habits that are costing them money, and
enforces the loss limits they set for themselves.

Why this and not "AI trade ideas": SEBI's own studies show roughly nine in ten retail F&O
traders lose money. What they lack is not ideas but discipline, visibility, and an honest
review of their own trading. And this product's own strategies currently fail their backtest
gate (see `docs/ROADMAP.md` Phase 4), so selling their output would be selling losses.

The strategy engine still exists as a secondary, free feature. It watches a universe of
instruments, sizes and scores its own trade ideas, and either executes them (intraday) or
hands them to the trader to approve or reject (long-term), per strategy on paper or live.

## The mechanism nobody else has

The engine does not emit tickers, it emits **fully-formed trades**: a size, an entry
reference, a stop, a target, the rule codes that fired, and a composite score whose AI
component is structurally capped at 30% and cannot rescue a trade the rules did not already
support. Approving one places exactly the trade the strategy asked for. The product's real
claim is *legible machine conviction* — you can always see why.

That cap is not a policy, it is enforced in the type system and covered by tests. See
`docs/ARCHITECTURE.md` §1.2.

## Who uses it

Today: one person, the operator, who is also the developer — experienced enough to read a
stop-loss and an R:R ratio without explanation, running this alongside a day job.

Where it is going: other traders, on their own broker accounts, with their own portfolios.
The trajectory is deliberate — auth, per-user data scoping, and per-user broker sessions are
built for it rather than retrofitted. The plan is freemium: the journal is free to start; history
beyond 30 days, insights, guardrails, and multiple brokers are paid. Billing is not built
until a free beta shows traders come back weekly (see `docs/ROADMAP.md` Phase 12).

## The real scene

**Mostly on a phone**, during the NSE session (09:15–15:30 IST), in short glances: between
meetings, on the move, at a desk only sometimes. The two questions that matter in those
glances are *"where am I today?"* and *"is there anything waiting for me to decide?"*.
Desktop is the occasional deep session. **Phone is the design target; desktop is not a
widened phone but it is second.**

Once real money is in play, a third question joins them: *"is anything running that I should
stop?"*

## Surfaces

| Surface | Mode | The visitor's success |
|---|---|---|
| Statement `/` | Operate | Real money only: search any stock and get full analysis + AI; today/month P&L from the broker's own trades (via the journal); guardrail alerts; real orders a live strategy placed, when there are any; tap any index for its level, chart, 52-week range and moving averages, plus an AI explanation of why it moved in its latest session (drivers, stocks behind it, global backdrop) and the headlines it was written from |
| Paper trading `/paper` | Operate | The engine's practice-money book, kept apart from real money: the track record first (net of charges, day by day and per strategy, win rate, profit factor, worst drawdown, against holding NIFTY), then today's paper P&L, paper trades and the pending-decision banner. With Kite or Upstox connected, the intraday run also paper-trades options: it buys an at-the-money call or put on an opening-range breakout in ten liquid F&O stocks, at live premiums, closed the same day |
| Decisions `/paper/decisions` | Operate | Triage pending AI proposals — approve or reject — split Intraday / Long-term. Approvals fill on paper |
| Holdings `/paper/holdings` | Operate | Paper equity curve, open paper positions marked live, closed paper trades |
| Engine `/paper/engine` | Operate | Start/stop an engine run, watch paper positions and fills; a "live mode armed" band names any strategy that will trade real money |
| Engine settings `/paper/settings` | Operate | The daily auto-run switch (paper-trade intraday every session, 09:15–15:30 IST, no Start button), the engine's sizing (account size, max exposure, per-trade cap), the daily scan and its universe, and each strategy's paper/live switch with what it still needs to go live (a passing backtest plus a paper record: 20 trading days, 30 trades, net profit after charges, profit factor 1.3, drawdown within 5% of account). Shows the daily loss limit read-only |
| Watchlist `/watchlist` | Operate | Tracked symbols at a glance |
| Scanner `/scanner` | Operate | On-demand bullish scan results |
| Option chain `/options` | Operate | Live NIFTY 50 / BANK NIFTY chain from the user's Upstox session: every strike's call and put premium, open interest and its change, IV, spot and put/call ratio. Read-only; also reached from those two index cards |
| Journal `/journal` | Review | P&L calendar, every broker trade auto-imported (options and futures included, each round trip marked CALL/PUT/FUT), stocks/options/futures P&L kept apart, notes and setup tags |
| Insights *(planned)* | Review | Plain-language findings about their own habits, e.g. "trades after 2 losses in a row: 31% win rate" |
| Settings `/settings` | Operate | Broker connection, guardrails (including the daily loss limit, which also trips the engine's kill-switch, and options limits: trades per day, lots per trade, a warning on unhedged option selling), AI model |
| Architecture `/system` | Explain | A live view of how the system fits together |
| Login `/login` | Operate | Google sign-in, nothing else |

## States that matter more than the happy path

- **Nothing pending.** The common case. An empty inbox must read as "you're clear", not as a
  broken page.
- **Live vs stale.** Data arrives over a WebSocket. The trader must always know whether a
  number is live, stale, or the socket is down — a stale P&L presented as current is the
  worst failure this product has.
- **Live mode armed.** Real money can move without further approval. This must be
  unmistakable at a glance and never inferable only from a settings page.
- **Kill-switch tripped.** The daily loss limit was hit and live trading has halted for the
  session. It does not re-arm on its own. The UI must say what stopped, when, and what is
  still open.
- **Market closed.** Most hours of most days. Prices do not move; the UI should say so
  rather than implying a frozen feed.
- **Decision pending, expiring.** Long-term suggestions expire after ~3 days.
- **Broker disconnected.** Kite tokens die daily at 06:00 IST; other brokers have their own
  expiries.
- **Loss.** Red numbers are a normal, frequent state, not an error condition.

## Constraints

- React 19 + Vite, plain JSX (no TypeScript), Tailwind v4, React Router 7.
- Existing deps that stay: recharts, framer-motion, lucide-react, axios.
- No component library and no test runner on the frontend.
- Bearer token in `localStorage`; refresh token in an httpOnly cookie, kept first-party by a
  Vercel rewrite. Backend on `*.nip.io`, frontend on Vercel.
- INR (₹) throughout. IST for every day boundary.

## Brand commitments

The visual world is already built and real in code — a broker's contract note, kept live.
See [`DESIGN.md`](DESIGN.md); its tokens are implemented in `frontend/src/index.css`, not
merely documented. New surfaces inherit it rather than inventing.

## Explicitly not this product

Not an advisor. NeoTrade never tells a user what to buy or sell for a fee. Recommending trades
for money needs SEBI Research Analyst registration, which this product does not have and
does not seek. Paid features are tools that work on the user's own trades and the user's own
rules: journal, insights, guardrails, and backtests of rules the user wrote. The engine's
suggestions are never a paid feature.

Not a broker — NeoTrade routes orders through the user's own broker and holds no funds. Not
social. Not a signal-selling service: no user's trades or scores are visible to another, and
nothing here is published as advice. No gamification of wins, no streaks, no confetti on a
profitable trade — this is someone's money model, and a design that celebrates a green day
will feel like mockery on a red one.

Once real orders are possible, one more rule: the product never places a trade the user
cannot reconstruct after the fact. Every live fill traces back to the intent, the rule codes,
and the score that produced it.
