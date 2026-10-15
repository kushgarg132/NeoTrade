import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, Circle } from 'lucide-react';
import Layout from '../components/Layout';
import Markdown from '../components/common/Markdown';
import MoneyBadge from '../components/common/MoneyBadge';
import StopAutopilot from '../components/common/StopAutopilot';
import { Sheet, Ruling, Money, StockIcon } from '../components/doc/Doc';
import api, { endpoints, getPreferences } from '../utils/api';
import { useRefetchOn } from '../hooks/useStream';
import { cn } from '../utils/cn';
import { formatCurrency, formatDateTime } from '../utils/formatters';

/**
 * Today: the first screen of the day. Can it trade (status strip), where is
 * my account (value, today's move, what moved and why), what do I do today
 * (exits, verdict changes, ideas, logins), me against the AI, and what the
 * AI has been doing. Everything comes from one call, GET /today;
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
        <Chip tone="bad" to={armed.autopilot ? '/ai/settings' : '/ai/settings'}>
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
    title="Do today"
    meta={items.length ? String(items.length + Math.max(hidden, 0)) : undefined}
    actions={
      <Link to="/mine/ideas" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">
        Ideas ›
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

/** Your own account right now: value, today's move, the overall gain, and
 *  the stocks that moved most with the headline behind each. Priced from
 *  market quotes, so it is live even when the broker is logged out. */
const Pulse = ({ pulse, failed, now }) => {
  if (failed) {
    return <Sheet title="Your account"><p className="doc-meta normal-case">Couldn’t price your account just now.</p></Sheet>;
  }
  if (!pulse) {
    return (
      <Sheet title="Your account">
        <p className="text-sm">No portfolio read yet.</p>
        <Link to="/mine/holdings" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">Read it from your broker ›</Link>
      </Sheet>
    );
  }
  const stale = pulse.holdings_as_of && now - new Date(pulse.holdings_as_of) > 36 * 3_600_000;
  return (
    <Sheet
      title="Your account"
      meta={`${pulse.count} holdings · as of ${formatDateTime(pulse.as_of)}`}
      actions={<Link to="/mine/holdings" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">Holdings ›</Link>}
    >
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <div>
          <p className="field-label mb-1">Value</p>
          <span className="figure-lg">{formatCurrency(pulse.value)}</span>
        </div>
        <div>
          <p className="field-label mb-1">Today</p>
          <Money value={pulse.day_change} size="lg" />
          {pulse.day_change_pct != null && <span className="doc-meta ml-1.5"><Money value={pulse.day_change_pct} percent className="text-sm" /></span>}
        </div>
        <div>
          <p className="field-label mb-1">Overall</p>
          <Money value={pulse.pnl} />
          {pulse.pnl_pct != null && <span className="doc-meta ml-1.5"><Money value={pulse.pnl_pct} percent className="text-sm" /></span>}
        </div>
      </div>
      {stale && (
        <p className="doc-meta normal-case mt-2">
          Holdings list from {formatDateTime(pulse.holdings_as_of)}: log in to your broker to refresh it.
        </p>
      )}
      {pulse.movers?.length > 0 && (
        <>
          <p className="field-label mt-3 mb-1">Moved most</p>
          <ul className="divide-y divide-[var(--rule)]">
            {pulse.movers.map((m) => (
              <li key={m.symbol} className="py-2 flex items-start gap-3">
                <StockIcon symbol={m.symbol} />
                <span className="flex-1 min-w-0">
                  <span className="block text-sm font-semibold">{m.symbol}</span>
                  <span className="block doc-meta normal-case">
                    {m.why?.title
                      ? (m.why.url ? <a href={m.why.url} target="_blank" rel="noreferrer" className="hover:underline">{m.why.title}</a> : m.why.title)
                      : 'No scored news on it.'}
                  </span>
                </span>
                <span className="text-right shrink-0">
                  <Money value={m.move_pct} percent className="text-sm" />
                  <span className="block"><Money value={m.day_change} className="text-xs" /></span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Sheet>
  );
};

/** AI against you: closed trades, net of charges, today and this month. */
const Scoreboard = ({ board, aiMode }) => (
  <Sheet title="You vs the AI" meta="closed trades, net of charges">
    {!board ? (
      <p className="doc-meta normal-case">Couldn’t load the scoreboard.</p>
    ) : (
      <div className="grid grid-cols-[auto_1fr_1fr] gap-x-4 gap-y-2 items-baseline">
        <span />
        <Link to="/mine/trades" className="field-label hover:text-[var(--stamp)]"><MoneyBadge kind="mine" /></Link>
        <Link to="/ai" className="field-label hover:text-[var(--stamp)]"><MoneyBadge kind="ai" mode={aiMode} /></Link>
        {[['Today', board.today], ['This month', board.month]].map(([label, row]) => (
          <React.Fragment key={label}>
            <span className="field-label">{label}</span>
            <Money value={row.mine} />
            <Money value={row.ai} />
          </React.Fragment>
        ))}
      </div>
    )}
  </Sheet>
);

// Hidden while there is nothing to show, unless the autopilot is on: its Stop button lives here.
const AiActivity = ({ rows, onStop, autopilotOn }) => (!rows?.length && !autopilotOn ? null : (
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
));

const REGIME = {
  risk_off: { label: 'Risk off', tone: 'bad' },
  risk_on: { label: 'Risk on', tone: 'good' },
  neutral: { label: 'Neutral', tone: 'neutral' },
};

/** The ingest worker's read of the market: regime, what drives it, the day's big events, and the brief. */
// The brief opens on its first lines; Show more appears only when there is more.
const Brief = ({ text }) => {
  const [open, setOpen] = useState(false);
  const [clipped, setClipped] = useState(false);
  const box = useRef(null);
  useLayoutEffect(() => {
    if (box.current) setClipped(box.current.scrollHeight > box.current.clientHeight + 1);
  }, [text]);
  return (
    <div>
      <p className="field-label mb-1">Market brief</p>
      <div ref={box} className={cn('overflow-hidden', !open && 'max-h-28')}>
        <Markdown className="text-sm text-[var(--ink-soft)]">{text}</Markdown>
      </div>
      {(clipped || open) && (
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
                className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">
          {open ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
};

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
      {brief && <Brief text={brief} />}
    </Sheet>
  );
};

const Today = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [autopilotOn, setAutopilotOn] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(tick);
  }, []);

  const load = () => {
    api.get(endpoints.today).then((res) => { setData(res.data); setNow(Date.now()); })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load today.'));
    getPreferences().then((res) => setAutopilotOn(!!res.data.autopilot_enabled)).catch(() => {});
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

  // A fill, a new idea, an autopilot order or a fresh holdings snapshot shows
  // now, not at the next minute's poll.
  useRefetchOn(['trades', 'suggestions', 'autopilot', 'portfolio', 'guardrails'], load);

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
      {/* Desktop: what needs deciding and the money on the left, the market as context on the right. */}
      <div className="private space-y-3 sm:space-y-4 max-w-3xl lg:max-w-6xl">
        <StatusStrip data={data} />
        <SetupChecklist setup={data.setup} />
        <div className="space-y-3 sm:space-y-4 lg:space-y-0 lg:grid lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:gap-4 lg:items-start">
          <div className="space-y-3 sm:space-y-4">
            <Pulse pulse={data.pulse} failed={!!data.errors?.pulse} now={now} />
            <NeedsYou items={data.needs_you || []} proposalsTotal={data.proposals_total} />
            <Scoreboard board={data.scoreboard} aiMode={data.autopilot ? (data.autopilot.live ? 'live' : 'paper') : undefined} />
            <AiActivity rows={data.ai_activity} onStop={stop} autopilotOn={autopilotOn} />
          </div>
          <div className="space-y-3 sm:space-y-4">
            <MarketBackdrop backdrop={data.backdrop} />
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default Today;
