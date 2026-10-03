import React from 'react';
import { ArrowDown } from 'lucide-react';
import Layout from '../components/Layout';
import { Sheet, Statement, Row, Cell, Tabs } from '../components/doc/Doc';
import { useTab } from '../hooks/useTab';
import { cn } from '../utils/cn';

/**
 * How the system fits together, as built. Static on purpose: it describes the
 * code, it does not read live state. Source of truth is docs/ARCHITECTURE.md;
 * when that document changes, this page follows it.
 */

/** One part of the system: what it is, and the module that is it. */
const Part = ({ title, where, children, tone, className }) => (
  <div
    className={cn(
      'border px-3 py-2.5 bg-[var(--paper)]',
      tone === 'stamp' ? 'border-[var(--stamp)]' : 'border-[var(--rule-strong)]',
      className
    )}
  >
    <p className={cn('field-label', tone === 'stamp' ? 'text-[var(--stamp)]' : 'text-[var(--ink)]')}>{title}</p>
    {children && <p className="mt-1 text-sm text-[var(--ink-soft)] leading-snug">{children}</p>}
    {where && <p className="mt-1 doc-meta normal-case break-words">{where}</p>}
  </div>
);

const Down = ({ label }) => (
  <div className="flex items-center justify-center gap-2 py-1.5 text-[var(--ink-faint)]" aria-hidden={!label}>
    <ArrowDown className="w-4 h-4" strokeWidth={1.5} />
    {label && <span className="doc-meta normal-case">{label}</span>}
  </div>
);

/** Parts side by side from sm up, stacked on a phone. */
const Side = ({ children, cols = 2 }) => (
  <div className={cn('grid gap-2', cols === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2')}>{children}</div>
);

const Overview = () => (
  <div className="space-y-3 sm:space-y-4">
    <Sheet title="System map" meta="Where each piece runs">
      <Part title="Your phone or browser" where="frontend/ · React 19 + Vite · Vercel project neotrade">
        Installs to the home screen. One WebSocket for live figures, REST for everything else.
      </Part>
      <Down label="HTTPS · /api/v1 · /api/v1/ws" />
      <Part title="Nginx + Let's Encrypt" where="neotrade.161.118.167.148.nip.io → 127.0.0.1:8000">
        TLS in front of the API on the VM.
      </Part>
      <Down />
      <Part title="FastAPI backend" where="backend/server.py · Docker container neotrade-backend · push-to-deploy">
        Routers, the trading engine, background loops. Google sign-in, 30-minute session JWT, rotating
        refresh cookie; every per-account record carries user_id.
      </Part>
      <Down label="reads and writes" />
      <Side cols={3}>
        <Part title="MongoDB Atlas" where="users, journal_trades, paper_*, suggestions, portfolio_snapshots …">
          The book of record.
        </Part>
        <Part title="Upstash Redis" where="broker tokens, caches, locks, pub/sub">
          Broker sessions, sentiment and verdict caches, job locks, cross-worker events.
        </Part>
        <Part title="OmniRoute gateway" where="backend/llm.py · prompts/*.md">
          The one LLM door: research, theses, portfolio review, index moves, chat.
        </Part>
      </Side>
      <Down label="outbound" />
      <Side>
        <Part title="Your broker" where="backend/brokers/ · Kite · Upstox · Angel One">
          Holdings, trades, positions, orders, option chains. Per-user, encrypted credentials.
        </Part>
        <Part title="Public market data" where="yfinance · NSE/BSE equity lists">
          Prices, history, fundamentals and headlines when no broker feed is live.
        </Part>
      </Side>
    </Sheet>

    <Sheet title="What the app does" meta="Feature → modules">
      <ul className="-my-1 divide-y divide-[var(--rule)]">
        {[
          ['Journal', 'Imports your broker trades, groups them into round trips, daily P&L calendar, notes', 'journal/ · routers/journal.py'],
          ['Patterns', 'Habits that cost money: time of day, after losses, size after a loss', 'journal/insights.py'],
          ['Guardrails', 'Daily loss cap, trades per day, cooldown; alerts and optional square-off', 'guardrails/ · risk/kill_switch.py'],
          ['Portfolio', 'Holdings from every broker, rule verdicts, AI review and action plan', 'portfolio/ · routers/portfolio.py'],
          ['Paper engine', 'Strategies trading practice money, scorecard, gates to go live', 'engine/ · strategies/ · risk/'],
          ['Decisions', 'Long-term proposals waiting for approve or decline', 'suggestions/'],
          ['Enquiry & markets', 'Stock analysis, indices, movers, option chains', 'research/ · routers/market_data.py · options/'],
        ].map(([feature, what, where]) => (
          <li key={feature} className="py-2">
            <p className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="figure-md text-sm">{feature}</span>
              <span className="doc-meta normal-case">{where}</span>
            </p>
            <p className="text-sm text-[var(--ink-soft)] leading-snug">{what}</p>
          </li>
        ))}
      </ul>
    </Sheet>
  </div>
);

const STRATEGIES = [
  ['volume_surge', 'Intraday', '5m', 'Volume spike with price confirmation'],
  ['vwap_reversion', 'Intraday', '5m', 'Stretch from VWAP snapping back'],
  ['orb_breakout', 'Intraday', '5m', 'Opening-range breakout'],
  ['rsi_momentum_scalp', 'Intraday', '5m', 'RSI momentum scalp'],
  ['orb_options', 'Intraday', '5m', 'ORB on F&O large-caps, buys the ATM call or put'],
  ['technical_breakout', 'Long-term', '1d', 'Breakout above resistance'],
  ['mean_reversion', 'Long-term', '1d', 'Oversold RSI below the lower band'],
  ['macd_crossover', 'Long-term', '1d', 'MACD bullish crossover'],
  ['quality_momentum', 'Long-term', '1d', 'Quality fundamentals with momentum'],
  ['analyst_verdict', 'Long-term', '1d', 'Cached AI analyst verdict, bounded by the AI cap'],
  ['cash_secured_put', 'Long-term', '1d', 'Sell a put on an oversold F&O stock'],
];

const Pipeline = () => (
  <div className="space-y-3 sm:space-y-4">
    <Sheet title="From a price bar to a trade" meta="The one decision path">
      <Part title="Price bar" where="engine/protocols.py · DataFeed">
        A 5-minute bar intraday, a daily bar long-term.
      </Part>
      <Down />
      <Part title="Strategy → Intent" where="strategies/ · core/models.py Intent">
        Side, strength 0–1, stop and target hints, and reason codes. No reasons, no intent.
      </Part>
      <Down />
      <Part title="Score: score_intent" where="scoring/composite.py · AI_CAP 0.30 · RULE_FLOOR 0.45" tone="stamp">
        Rules first. News sentiment moves the score by 30% at most, and a trade the rules scored under
        0.45 is dropped — the AI cannot rescue it.
      </Part>
      <Down />
      <Part title="Size: size_intents" where="engine/runner.py · components/risk/risk.py RiskRules">
        Risk per trade scales with conviction. Per-trade cap, exposure cap, and the daily-loss kill-switch
        stop new intraday orders for the day once tripped.
      </Part>
      <Down label="route" />
      <Side>
        <Part title="Intraday → executes" where="engine/execution/ · RoutingExecutionClient">
          On paper by default. Live only when you switch the strategy live, the broker session is active,
          it passed the backtest gate and its paper record passed the paper gate.
        </Part>
        <Part title="Long-term → Decisions" where="suggestions/sink.py · store.py">
          Waits for you. Approve fills at a fresh price; proposals expire after 3 days.
        </Part>
      </Side>
      <Down />
      <Part title="Ledger" where="engine/persistence.py LedgerStore · venue paper | live">
        Orders, fills, positions and round trips, paper and live kept in separate books.
      </Part>
    </Sheet>

    <Sheet title="Gates to real money" meta="Enforced in code">
      <Side cols={3}>
        <Part title="Backtest gate" where="risk/backtest_gate.py">
          ≥1 year, ≥30 trades, profit factor ≥1.3, drawdown ≤15%.
        </Part>
        <Part title="Paper gate" where="risk/paper_gate.py">
          20 trading days, 30 trades, net profit after charges, profit factor 1.3, drawdown within 5%.
        </Part>
        <Part title="Kill-switch" where="risk/kill_switch.py">
          Daily loss limit hit: no new intraday orders until tomorrow. Never re-arms by itself.
        </Part>
      </Side>
    </Sheet>

    <Sheet title="Registered strategies" meta={`${STRATEGIES.length}`}>
      <ul className="-my-1 divide-y divide-[var(--rule)]">
        {STRATEGIES.map(([name, mode, bar, trigger]) => (
          <li key={name} className="py-2">
            <p className="flex items-baseline justify-between gap-3">
              <span className="figure-md text-sm truncate">{name}</span>
              <span className="doc-meta normal-case shrink-0">{mode} · {bar}</span>
            </p>
            <p className="text-sm text-[var(--ink-soft)] leading-snug">{trigger}</p>
          </li>
        ))}
      </ul>
      <p className="doc-meta normal-case pt-3">From strategies/registry.py. None has passed the backtest gate yet, so all trade on paper.</p>
    </Sheet>
  </div>
);

const Data = () => (
  <div className="space-y-3 sm:space-y-4">
    <Sheet title="Broker adapters" meta="brokers/protocol.py BrokerAdapter">
      <Statement
        columns={[
          { key: 'what', label: 'Capability' },
          { key: 'kite', label: 'Kite' },
          { key: 'upstox', label: 'Upstox' },
          { key: 'angel', label: 'Angel One' },
        ]}
      >
        {[
          ['Connect', 'Redirect', 'Redirect', 'Client code + TOTP'],
          ['Live ticks', 'Kite ticker', 'Market-data WebSocket', 'Polling'],
          ['Holdings', 'Yes, with MFs', 'Yes', 'Yes'],
          ["Today's trades", 'Yes', 'Yes', 'Yes'],
          ['Trade history', 'Console CSV', 'API, a year', '—'],
          ['Equity orders', 'Yes', 'Yes', 'Yes'],
          ['Option orders', 'Yes', 'Yes', '—'],
          ['Option chain', '—', 'NIFTY, BANK NIFTY', '—'],
        ].map(([what, kite, upstox, angel]) => (
          <Row key={what}>
            <Cell className="figure-md">{what}</Cell>
            <Cell>{kite}</Cell>
            <Cell>{upstox}</Cell>
            <Cell>{angel}</Cell>
          </Row>
        ))}
      </Statement>
      <p className="doc-meta normal-case pt-3">
        One adapter per user, built from that user's encrypted credentials (Fernet). Tokens cached in Redis per
        user and broker.
      </p>
    </Sheet>

    <Sheet title="Market data" meta="Best source first">
      <Part title="Broker stream" where="data/feeds/live_kite.py · live_upstox.py · tick_bars.py">
        Ticks aggregated into bars when Kite or Upstox is connected.
      </Part>
      <Down label="otherwise" />
      <Part title="Polling" where="data/feeds/polling_live.py · YFinanceProvider">
        A quote per symbol each minute; a symbol with no quote is skipped, not fatal.
      </Part>
      <Down label="history, fundamentals, news" />
      <Part title="yfinance + caches" where="market_cache.py · instruments/ (seed + NSE/BSE lists)">
        Daily history, fundamentals and headlines, cached; the instrument master merges the seed file, the
        free exchange lists and the broker's own dump.
      </Part>
    </Sheet>

    <Sheet title="Live updates to your screen" meta="ws/">
      <Part title="Hub" where="ws/hub.py · ws/routes.py /api/v1/ws">
        One authenticated socket per tab, topics per user: prices, P&L, trades, suggestions, runs, guardrails.
      </Part>
      <Down label="across workers" />
      <Part title="Redis pub/sub" where="broadcast.py">
        Any worker publishes; whichever worker holds your socket delivers.
      </Part>
    </Sheet>
  </div>
);

const JOBS = [
  ['Paper auto-run', 'Every 60s, 09:15–15:30 IST weekdays', 'Keeps one intraday paper run alive for users who turned it on; one worker owns it through a Redis key', 'engine/autorun.py'],
  ['Guardrail monitor', 'Every minute, 09:15–15:35 IST', "Syncs today's trades, checks your limits, alerts once per breach, trips the kill-switch", 'guardrails/monitor.py'],
  ['Price & P&L pump', 'Every 15s', 'Marks open positions and pushes P&L to open sockets', 'ws/pump.py'],
  ['Daily pass', '16:00 IST', 'Expires stale suggestions, closes expired options, refreshes analyst verdicts, runs each scan, syncs every journal', 'scheduler.py'],
  ['Weekly portfolio review', 'Friday, in the daily pass', 'Re-reviews holdings, alerts when a verdict gets worse', 'portfolio/service.py'],
];

const Jobs = () => (
  <div className="space-y-3 sm:space-y-4">
    <Sheet title="Background jobs" meta="Started in server.py">
      <Statement
        columns={[
          { key: 'job', label: 'Job' },
          { key: 'when', label: 'When' },
          { key: 'what', label: 'What it does' },
          { key: 'where', label: 'Code' },
        ]}
      >
        {JOBS.map(([job, when, what, where]) => (
          <Row key={job}>
            <Cell className="figure-md">{job}</Cell>
            <Cell className="doc-meta normal-case">{when}</Cell>
            <Cell className="text-[var(--ink-soft)]">{what}</Cell>
            <Cell className="doc-meta normal-case">{where}</Cell>
          </Row>
        ))}
      </Statement>
      <p className="doc-meta normal-case pt-3">
        Two workers run side by side; Redis locks make each job run once, not once per worker.
      </p>
    </Sheet>

    <Sheet title="Deploys" meta="Push to main">
      <Side>
        <Part title="Backend" where="GitHub Actions on a self-hosted runner">
          CI runs the tests; a passing run rebuilds the container on the VM when backend/ changed.
        </Part>
        <Part title="Frontend" where="Vercel git integration">
          Every push to main builds and serves the new app.
        </Part>
      </Side>
    </Sheet>
  </div>
);

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'data', label: 'Data' },
  { id: 'jobs', label: 'Jobs' },
];

const SystemArchitecturePage = () => {
  const [tab, setTab] = useTab(TABS.map((t) => t.id));
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-4xl">
        <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Architecture sections" />
        {tab === 'overview' && <Overview />}
        {tab === 'pipeline' && <Pipeline />}
        {tab === 'data' && <Data />}
        {tab === 'jobs' && <Jobs />}
      </div>
    </Layout>
  );
};

export default SystemArchitecturePage;
