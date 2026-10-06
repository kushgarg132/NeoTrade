import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, Circle } from 'lucide-react';
import Layout from '../components/Layout';
import Markdown from '../components/common/Markdown';
import MoneyBadge from '../components/common/MoneyBadge';
import StopAutopilot from '../components/common/StopAutopilot';
import { Sheet, Ruling, Money, StockIcon } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { formatCurrency, formatDateTime } from '../utils/formatters';

/**
 * Today: the first screen of the day. Can it trade (status strip), what
 * needs me (setup, Needs you), where am I (P&L for my money and the AI's),
 * and what the AI has been doing. Everything comes from one call, GET /today;
 * a part that failed says so in place and the rest still shows.
 */

const NAMES = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };

const Chip = ({ to, tone = 'neutral', children }) => {
  const cls = cn(
    'inline-flex items-center gap-1.5 h-8 px-2.5 text-xs border whitespace-nowrap',
    tone === 'good' && 'border-[var(--gain)] text-[var(--gain)]',
    tone === 'bad' && 'border-[var(--loss)] text-[var(--loss)] bg-[var(--loss-wash)]',
    tone === 'neutral' && 'border-[var(--rule-strong)] text-[var(--ink-soft)]',
  );
  return to ? <Link to={to} className={cls}>{children}</Link> : <span className={cls}>{children}</span>;
};

const StatusStrip = ({ data }) => {
  const { market, accounts, live_armed: armed, kill_switch: kill } = data;
  return (
    <div className="sticky top-0 z-20 -mx-3 px-3 py-2 sm:-mx-4 sm:px-4 bg-[var(--paper)] border-b border-[var(--rule-strong)] flex flex-wrap gap-1.5">
      <Chip tone={market?.open ? 'good' : 'neutral'}>
        <Circle className={cn('w-2 h-2', market?.open && 'fill-current')} />
        {market?.open ? 'Market open' : 'Market closed'}
      </Chip>
      {accounts === null && <Chip tone="bad">Broker status unavailable</Chip>}
      {Object.entries(accounts || {}).map(([role, info]) => {
        const name = `${NAMES[info.broker] || info.broker}${role === 'ai' ? ' · AI' : ''}`;
        return info.state === 'ACTIVE'
          ? <Chip key={role} tone="good"><Check className="w-3 h-3" />{name}</Chip>
          : <Chip key={role} tone="bad" to="/settings?tab=accounts">{name} · log in ›</Chip>;
      })}
      {(armed?.autopilot || armed?.strategies?.length > 0) && (
        // Goes where the armed thing is switched off: the autopilot under AI, strategies in Practice setup.
        <Chip tone="bad" to={armed.autopilot ? '/ai/autopilot' : '/practice/setup'}>
          ▲ LIVE armed{armed.autopilot ? ' · autopilot' : ''}{armed.strategies?.length ? ` · ${armed.strategies.length} strateg${armed.strategies.length === 1 ? 'y' : 'ies'}` : ''}
        </Chip>
      )}
      {kill?.tripped && <Chip tone="bad" to="/settings?tab=safety">Loss limit hit · trading stopped</Chip>}
    </div>
  );
};

const SetupChecklist = ({ setup }) => {
  if (!setup || setup.done === setup.total) return null;
  return (
    <Sheet title="Set up NeoTrade" meta={`${setup.done}/${setup.total}`}>
      <ul className="divide-y divide-[var(--rule)]">
        {setup.steps.map((step) => (
          <li key={step.id}>
            <Link to={step.link} className="flex items-center gap-3 py-2.5 min-h-11 text-sm hover:text-[var(--stamp)]">
              {step.done
                ? <Check className="w-4 h-4 text-[var(--gain)] shrink-0" />
                : <Circle className="w-4 h-4 text-[var(--ink-faint)] shrink-0" />}
              <span className={cn('flex-1', step.done && 'text-[var(--ink-faint)] line-through')}>{step.label}</span>
              {!step.done && <ArrowRight className="w-4 h-4 text-[var(--ink-faint)]" />}
            </Link>
          </li>
        ))}
      </ul>
    </Sheet>
  );
};

const expiresIn = (iso) => {
  if (!iso) return null;
  const hours = (new Date(iso) - Date.now()) / 3_600_000;
  if (hours <= 0) return 'expired';
  return hours < 24 ? `expires in ${Math.ceil(hours)}h` : `expires in ${Math.ceil(hours / 24)}d`;
};

/** A proposal's row says what approving costs and how sure the engine is, so a
 *  glance is enough to know whether to open Decisions now. */
const proposalLine = (item) =>
  [
    item.conviction != null && `conviction ${item.conviction.toFixed(2)}`,
    expiresIn(item.expires_at),
  ].filter(Boolean).join(' · ');

const NeedsYou = ({ items, proposalsTotal }) => {
  const shown = items.filter((item) => item.kind === 'proposal').length;
  const hidden = (proposalsTotal || 0) - shown;
  return (
  <Sheet
    title="Needs you"
    meta={items.length ? String(items.length + Math.max(hidden, 0)) : undefined}
    actions={
      <Link to="/practice/decisions" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">
        All decisions ›
      </Link>
    }
  >
    {items.length === 0 ? (
      <p className="font-[family-name:var(--font-narrow)] text-2xl font-bold uppercase tracking-[0.06em] py-4">You’re clear.</p>
    ) : (
      <ul className="divide-y divide-[var(--rule)]">
        {items.map((item, i) => {
          const body = (
            <>
              {item.kind === 'proposal' && <StockIcon symbol={item.symbol} />}
              <span className="flex-1 min-w-0">
                <span className="block text-sm font-semibold truncate">{item.title}</span>
                <span className="block doc-meta normal-case truncate">
                  {item.kind === 'proposal'
                    ? proposalLine(item)
                    : [item.detail, expiresIn(item.expires_at)].filter(Boolean).join(' · ')}
                </span>
              </span>
              {item.kind === 'proposal' && item.notional != null && (
                <span className="figure-md text-sm shrink-0">{formatCurrency(item.notional)}</span>
              )}
              {item.link && <ArrowRight className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />}
            </>
          );
          return (
            <li key={`${item.kind}-${i}`}>
              {item.link
                ? <Link to={item.link} className="flex items-center gap-3 py-2.5 min-h-11 hover:text-[var(--stamp)]">{body}</Link>
                : <div className="flex items-center gap-3 py-2.5 min-h-11">{body}</div>}
            </li>
          );
        })}
      </ul>
    )}
  </Sheet>
  );
};

const PnlSplit = ({ pnl, aiMode, market, loadedAt, now }) => (
  <Sheet title="Today" meta={market?.open
    ? `updated ${Math.max(0, Math.round((now - loadedAt) / 1000))}s ago`
    : `Market closed · as of ${formatDateTime(market?.as_of)}`}>
    {pnl === null ? (
      <p className="doc-meta normal-case">Couldn’t load today’s P&amp;L.</p>
    ) : (
      <div className="grid grid-cols-2 gap-3">
        <Link to="/mine/trades" className="block p-2 -m-2 hover:bg-[var(--paper-sunk)]">
          <p className="field-label mb-1"><MoneyBadge kind="mine" /> · closed, gross</p>
          <Money value={pnl.mine} size="lg" />
        </Link>
        <Link to="/ai" className="block p-2 -m-2 hover:bg-[var(--paper-sunk)]">
          <p className="field-label mb-1"><MoneyBadge kind="ai" mode={aiMode} /> · closed</p>
          <Money value={pnl.ai} size="lg" />
        </Link>
      </div>
    )}
  </Sheet>
);

const AiActivity = ({ rows, onStop, autopilotOn }) => (
  <Sheet
    title="AI activity"
    actions={<StopAutopilot on={autopilotOn} onStopped={onStop} />}
  >
    {!rows || rows.length === 0 ? (
      <p className="doc-meta normal-case">Nothing from the autopilot yet.</p>
    ) : (
      <ul className="divide-y divide-[var(--rule)]">
        {rows.map((row, i) => (
          <li key={`${row.at}-${i}`} className="py-2 text-sm flex items-baseline gap-2">
            <span className={cn('field-label', row.status === 'FILLED' ? 'text-[var(--gain)]' : row.status === 'SENT' ? 'text-[var(--ink-soft)]' : 'text-[var(--loss)]')}>
              {row.status === 'FILLED' ? (row.side === 'BUY' ? 'Bought' : 'Sold') : row.status === 'SENT' ? 'Sent' : 'Refused'}
            </span>
            <span className="flex-1 min-w-0 truncate">
              {row.quantity} {row.symbol}
              {row.status === 'SENT' ? ' · with the broker, not filled yet' : row.status !== 'FILLED' && row.reason ? ` · ${row.reason}` : ''}
            </span>
            <span className="doc-meta shrink-0">{formatDateTime(row.at)}</span>
          </li>
        ))}
      </ul>
    )}
    <Link to="/ai/activity" className="field-label text-[var(--stamp)] hover:underline inline-block mt-2">All activity ›</Link>
  </Sheet>
);

const REGIME = {
  risk_off: { label: 'Risk off', tone: 'bad' },
  risk_on: { label: 'Risk on', tone: 'good' },
  neutral: { label: 'Neutral', tone: 'neutral' },
};

/** The ingest worker's read of the market: regime, what drives it, the day's big events, and the brief. */
const MarketBackdrop = ({ backdrop }) => {
  const { regime, brief, events = [] } = backdrop || {};
  if (!regime && !brief && !events.length) return null;
  const shown = REGIME[regime?.label];
  return (
    <Sheet
      title="Markets"
      actions={<Link to="/research/news" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">News ›</Link>}
    >
      {regime && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {shown && <Chip tone={shown.tone}>{shown.label}</Chip>}
          {(regime.drivers || []).map((d) => <Chip key={d}>{d}</Chip>)}
        </div>
      )}
      {events.length > 0 && (
        <ul className="mb-2 text-sm">
          {events.slice(0, 4).map((e) => (
            <li key={`${e.at}-${e.title}`} className="doc-meta normal-case">
              {formatDateTime(e.at)} · {e.country} {e.title}{e.forecast ? ` · forecast ${e.forecast}` : ''}
            </li>
          ))}
        </ul>
      )}
      {brief && (
        <details>
          <summary className="field-label cursor-pointer min-h-9 inline-flex items-center">Market brief</summary>
          <Markdown className="text-sm text-[var(--ink-soft)]">{brief}</Markdown>
        </details>
      )}
    </Sheet>
  );
};

const Today = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [autopilotOn, setAutopilotOn] = useState(false);
  const [loadedAt, setLoadedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(tick);
  }, []);

  const load = () => {
    api.get(endpoints.today).then((res) => { setData(res.data); setLoadedAt(Date.now()); setNow(Date.now()); })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load today.'));
    api.get(endpoints.settings.preferences).then((res) => setAutopilotOn(!!res.data.autopilot_enabled)).catch(() => {});
  };
  useEffect(() => {
    load();
    // Not polled in a hidden tab; fresh again the moment it is shown.
    const timer = setInterval(() => !document.hidden && load(), 60_000);
    const onShow = () => !document.hidden && load();
    document.addEventListener('visibilitychange', onShow);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onShow);
    };
  }, []);

  const stop = () => setAutopilotOn(false);

  if (!data) {
    return (
      <Layout>
        <div className="max-w-3xl">{error ? (
          <Sheet title="Today">
            <p className="text-sm">{error}</p>
            <button type="button" onClick={() => { setError(null); load(); }} className="mt-2 min-h-11 px-3 text-sm border border-[var(--rule-strong)]">Retry</button>
          </Sheet>
        ) : <Sheet title="Today"><Ruling rows={5} /></Sheet>}</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="private space-y-3 sm:space-y-4 max-w-3xl">
        <StatusStrip data={data} />
        <SetupChecklist setup={data.setup} />
        <NeedsYou items={data.needs_you || []} proposalsTotal={data.proposals_total} />
        <PnlSplit pnl={data.pnl_today} aiMode={data.autopilot ? (data.autopilot.live ? 'live' : 'paper') : undefined} market={data.market} loadedAt={loadedAt} now={now} />
        <AiActivity rows={data.ai_activity} onStop={stop} autopilotOn={autopilotOn} />
        <MarketBackdrop backdrop={data.backdrop} />
        <Link to="/research" className="flex items-center justify-between gap-3 sheet px-3 py-2.5 sm:px-4 hover:bg-[var(--paper-sunk)]">
          <span className="text-sm"><span className="field-label">Markets</span> · NIFTY, BANK NIFTY, movers and news</span>
          <ArrowRight className="w-4 h-4 text-[var(--ink-faint)]" />
        </Link>
      </div>
    </Layout>
  );
};

export default Today;
