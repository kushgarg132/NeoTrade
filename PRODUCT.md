# NeoTrade — product truth

> What this product is and who it serves. For how it is built, see
> the handbook in [`frontend/src/handbook/`](frontend/src/handbook/) (in the app at `/system`); for what gets built next, see
> [`docs/ROADMAP.md`](docs/ROADMAP.md).

## What it is

**Two broker accounts and one daily answer**, for a trader in **Indian equities** (since
Phase 19, 2026-10-14; spec `docs/superpowers/specs/2026-10-14-two-accounts-reset-design.md`).

- **Mine** — the trader's own account (role `mine`). NeoTrade reads its holdings every day,
  says where the account stands and what moved and why, gives each holding a verdict
  (hold / add / trim / sell), alerts on exit levels, journals the trades, and enforces the loss
  limits the trader set. It never trades this account on its own: every order here is the
  trader's two-tap decision.
- **AI** — a second broker account the app runs (role `ai`): the strategy engine, the
  long-term scan, news and the autopilot. It trades **on paper until a strategy earns live
  money** (a passing backtest plus a passing paper record), then on capped capital.
- **The link:** an idea reaches the trader's account only from a strategy proven on the AI
  account (`risk/paper_gate.py::for_mine`). The two accounts compete, AI against the trader,
  net of charges, on Today.

Why: the strategies do not yet pass their gates, so handing their raw output to the trader
would be handing over losses. The AI account is where an idea earns trust; the trader's own
account gets the daily review and only the ideas that earned it.

## The mechanism nobody else has

The engine does not emit tickers, it emits **fully-formed trades**: a size, an entry
reference, a stop, a target, the rule codes that fired, and a composite score whose AI
component is structurally capped at 30% and cannot rescue a trade the rules did not already
support. Approving one places exactly the trade the strategy asked for. The product's real
claim is *legible machine conviction* — you can always see why.

That cap is not a policy, it is enforced in the type system and covered by tests. See
[`frontend/src/handbook/trading-and-money.md`](frontend/src/handbook/trading-and-money.md), "The invariants".

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

Navigation (since 2026-10-14): **Today · Mine · AI · Research · More**, the same five on the
phone's bottom bar; old paths redirect. Mine is the trader's own account (Overview · Holdings · Tax · Journal, plus a page per stock; the
badge on Mine counts open "Needs you" items); AI is the account the app runs (Overview · Activity ·
Book · Strategies · Settings; "Practice" is gone, it is the AI account on paper); More is setup.
Rows below that still name Practice, Decisions or the Scanner describe their old place: Decisions
is the Needs you list on Mine → Overview, Practice → Engine is AI → Overview, Book / Strategies / Setup are AI → Book /
Strategies / Settings, and the bullish Scanner and paper approvals are gone.

| Surface | Mode | The visitor's success |
|---|---|---|
| Today `/` | Operate | The first screen of the day (one `GET /today` call): a sticky status strip (market open/closed, each account's broker session with a log-in link, LIVE armed, loss-limit stop), a setup checklist until done, **Your account** (value, today's move and overall gain on one line, then the top three Needs-you items and "See all in Mine"), **Do today** (logins, exit alerts on positions you placed through the app, verdict changes, ideas from proven strategies, waiting cards, guardrail alerts, or "You're clear."), **You vs the AI** (closed, net of charges, today and this month), and the autopilot's last moves with a Stop button. The same answer goes to Telegram at 08:45 and after the 16:00 pass |
| Research → Search `/research` | Operate | Real money only: search any stock and get full analysis + AI; today/month P&L from the broker's own trades (via the journal); guardrail alerts; real orders a live strategy placed, when there are any; tap any index for its level, chart, 52-week range and moving averages, plus an AI explanation of why it moved in its latest session (drivers, stocks behind it, global backdrop) and the headlines it was written from |
| Practice → Engine `/practice` | Operate | What the strategy engine is doing now, on practice money (never the AI autopilot): the live-mode-armed warning, the intraday run with Start/Stop and live progress (it also paper-trades ATM options on ORB breakouts in ten F&O stocks when Kite or Upstox is connected), the long-term engine with its next scan and Scan button, **today net of charges**, today's fills, and a line to Strategies with how many are ready for real money. Old `?book=` links go to Strategies |
| AI → Decisions `/ai/decisions` | Operate | The engine's long-term proposals and the chat's / order ticket's waiting cards — approve or decline. Approvals fill on paper, or with real money on the user's own account after a second confirming tap. Nothing here trades the AI account |
| Practice → Book `/practice/book` | Review | How the practice money is doing: one figure **net of charges** for Today / Month / All time (`?period=`) with its curve, closed count and win rate; open positions as compact rows (unrealised, "at last close" after hours) with Sell / Add behind a tap; open orders; the latest executions |
| Practice → Strategies `/practice/strategies` | Review | Whether any strategy is good enough for real money: per strategy its status, paper record and what it still needs (a passing backtest plus 20 trading days, 30 trades, net profit, profit factor 1.3, drawdown within 5%), tap for what it is for; then the track record net of charges against NIFTY (`?book=` Intraday / Long term / All), every paper trade, and what the engine learned. Strategies the weekly AI builder drafted and tested show with a Built badge, its thesis and year / last-90-day results; the rejected ones fold under Tried and rejected. **New strategy** composes your own from the same blocks (live preview, then Test it); **Mine** lists yours (Testing / Active / Rejected / Retired, verdict, year and last-90-day lines, Retire and Re-test), private to you, with limits of 3 a day, one testing at a time and 5 active per horizon. A **Horizon** choice (Intraday / Swing) starts the form: a swing strategy buys on daily-bar signals and holds up to a chosen number of days (long only), and must also beat buy-and-hold of the same stocks to go active; rows carry an Intraday / Swing chip. `/practice/library` redirects |
| Practice → Setup `/practice/setup` | Operate | The engine's sizing (account size, max exposure, per-trade cap, read-only; edited on AI → Autopilot) and each strategy's paper/live switch with what it still needs to go live (a passing backtest plus a paper record: 20 trading days, 30 trades, net profit after charges, profit factor 1.3, drawdown within 5% of account). Shows the daily loss limit read-only |
| Research → Watchlist `/research/watchlist` | Operate | Tracked symbols at a glance |
| Research → Scanner `/research/scanner` | Operate | On-demand **bullish scan** results (not the engine's long-term scan, which feeds AI → Decisions) |
| Research → Options `/research/options` | Operate | Live NIFTY 50 / BANK NIFTY chain from the user's Upstox session: every strike's call and put premium, open interest and its change, IV, spot and put/call ratio. Read-only; also reached from those two index cards |
| Mine → Overview `/mine` | Review | The depth behind Today. Headline: value, today's move, total gain, **XIRR** and NIFTY's XIRR on the same cash flows (from `mine_daily`, replayed from the journal's trades). A value curve (1M / 6M / 1Y / All) against net invested and NIFTY, **Needs you** (one ranked list: verdict changes, target/stop levels, ideas from proven strategies, rebalance buys, results dates; dismiss or snooze 7 days; "You're clear." when empty), waiting cards, what drove the gain, and the mix |
| Mine → Holdings `/mine/holdings` | Review | Long-term holdings from every connected broker merged by ISIN, one line each: weight, value, day and total move, verdict stamp (SELL / HOLD / ADD, funds REVIEW / KEEP; admin-only until `portfolio_verdicts` is set to all, needs SEBI RA registration) and progress toward your target. Sort by weight / day / gain / verdict, filter Needs you / Stocks / Funds; tap a row for the stock page. **Plan new money** opens the rebalance sheet. The old Plan and Review sub-tabs are gone; the daily review still runs and a Telegram alert fires when a verdict gets worse |
| Mine → Stock `/mine/stock/:symbol` | Review | One holding: position, XIRR, tax lots (days to long-term, estimated tax if sold), price chart with your buys and sells and your target/stop, **your thesis** (why, target, stop, review-by; target and stop raise alerts), verdict and its history, next results and ex-dividend dates, dividends received, news, Sell / Add through the order ticket. A sold holding still opens |
| Mine → Tax `/mine/tax` | Review | Indian FY capital gains from the journal, FIFO: short-term (20%) and long-term (12.5% above Rs 1.25 lakh), exemption used and left, estimated tax, unrealised by lot, lots turning long-term soon, and loss / gain harvesting before 31 March. Estimate, not tax advice; pre-2018 grandfathering and F&O business income are not covered |
| Mine → Journal `/mine/journal` | Review | The user's own account (role `mine`). Trades: P&L calendar, every broker trade auto-imported (options and futures included, each round trip marked CALL/PUT/FUT), stocks/options/futures P&L kept apart, notes and setup tags; Habits is an inner tab (`/mine/trades` and `/mine/habits` redirect here) |
| Insights *(planned)* | Review | Plain-language findings about their own habits, e.g. "trades after 2 losses in a row: 31% win rate" |
| Margin note (chat, every page) | Operate | Ask about your own portfolio, journal, paper engine, proposals and limits, or a stock, and get the answer from your data. It can prepare any change the app makes -- approve or decline a proposal, start or stop the paper run, change a limit, place an NSE equity market order on paper or live -- as a card that does nothing until you tap Confirm (twice for a live order); every check runs again at confirm |
| AI → Overview / Activity / Autopilot `/ai`, `/ai/activity`, `/ai/autopilot` | Operate | The AI account (role `ai`) only: autopilot on/off and mode, capital deployed vs its limit, today's P&L (badged `AI · paper` or `AI · live`), what the autopilot did today, the monthly AI vs you table; every autopilot order and refusal with Stop; the autopilot's switch, live mode (typed confirmation) and fence first, then the engine that feeds it (intraday paper every session, 09:15–15:30 IST, experimental: it loses money after charges in every backtest so far; the 4 PM long-term scan over the user's universe; the long-term paper book; the scan and the long-term pass are kept on while the autopilot is on), then the trading limits. Live, the autopilot takes only proposals from strategies that passed both gates |
| Handbook `/system` (admin) | Read | The operator's reference: how every part works (`frontend/src/handbook/*.md`: System & Data, Trading & Money, AI & News, Jobs & Ops, Journey) with live panels from `GET /system/status` — deploy commits, each job's last run, news ingest, data sizes, AI budgets. Reached from More → About |
| Future `/system/future` (admin) | Operate | The project's backlog: add, edit, reorder and close items by area and status (`backlog` collection), seeded from the roadmap and audits |
| More (Settings) `/settings` | Operate | Tabs Accounts (brokers + which is yours / the AI's) · Safety · AI · About. Broker connection, guardrails (including the daily loss limit, which also trips the engine's kill-switch, and options limits: trades per day, lots per trade, a warning on unhedged option selling), AI model |
| More → About → Architecture `/system` | Explain | A live view of how the system fits together |
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

Not an advisor. NeoTrade never tells a user what to buy or sell for a fee. The one exception built so far, the Portfolio page's SELL / HOLD / ADD, is shown to admins only (`portfolio_verdicts: admin`) and must stay that way until the product holds SEBI Research Analyst registration. Recommending trades
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
and the score that produced it -- or, for an order placed from the chat, to the user's own
message and their confirming tap (stored on the `chat_actions` record and as `reason` on the
`live_orders` record, `strategy_name="chat"`).
