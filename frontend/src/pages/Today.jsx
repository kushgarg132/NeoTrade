import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, Circle } from 'lucide-react';
import Layout from '../components/Layout';
import { Sheet, Ruling, Money } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { formatDateTime } from '../utils/formatters';

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
        <Chip tone="bad" to="/ai/limits">
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

const NeedsYou = ({ items }) => (
  <Sheet title="Needs you" meta={items.length ? String(items.length) : undefined}>
    {items.length === 0 ? (
      <p className="font-[family-name:var(--font-narrow)] text-2xl font-bold uppercase tracking-[0.06em] py-4">You’re clear.</p>
    ) : (
      <ul className="divide-y divide-[var(--rule)]">
        {items.map((item, i) => {
          const body = (
            <>
              <span className="flex-1 min-w-0">
                <span className="block text-sm font-semibold truncate">{item.title}</span>
                <span className="block doc-meta normal-case truncate">
                  {[item.detail, expiresIn(item.expires_at)].filter(Boolean).join(' · ')}
                </span>
              </span>
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

const PnlSplit = ({ pnl, market }) => (
  <Sheet title="Today" meta={market?.open ? 'live' : `Market closed · as of ${formatDateTime(market?.as_of)}`}>
    {pnl === null ? (
      <p className="doc-meta normal-case">Couldn’t load today’s P&amp;L.</p>
    ) : (
      <div className="grid grid-cols-2 gap-3">
        <Link to="/mine/trades" className="block p-2 -m-2 hover:bg-[var(--paper-sunk)]">
          <p className="field-label mb-1"><span className="badge-mine">Mine</span> · closed, gross</p>
          <Money value={pnl.mine} size="lg" />
        </Link>
        <Link to="/ai" className="block p-2 -m-2 hover:bg-[var(--paper-sunk)]">
          <p className="field-label mb-1"><span className="badge-ai">AI</span> · closed</p>
          <Money value={pnl.ai} size="lg" />
        </Link>
      </div>
    )}
  </Sheet>
);

const AiActivity = ({ rows, onStop, autopilotOn }) => (
  <Sheet
    title="AI activity"
    actions={autopilotOn ? (
      <button type="button" onClick={onStop} className="h-8 px-3 text-xs border border-[var(--loss)] text-[var(--loss)]">🛑 Stop</button>
    ) : null}
  >
    {!rows || rows.length === 0 ? (
      <p className="doc-meta normal-case">Nothing from the autopilot yet.</p>
    ) : (
      <ul className="divide-y divide-[var(--rule)]">
        {rows.map((row, i) => (
          <li key={`${row.at}-${i}`} className="py-2 text-sm flex items-baseline gap-2">
            <span className={cn('field-label', row.status === 'FILLED' ? 'text-[var(--gain)]' : 'text-[var(--loss)]')}>
              {row.status === 'FILLED' ? (row.side === 'BUY' ? 'Bought' : 'Sold') : 'Refused'}
            </span>
            <span className="flex-1 min-w-0 truncate">{row.quantity} {row.symbol}{row.status !== 'FILLED' && row.reason ? ` · ${row.reason}` : ''}</span>
            <span className="doc-meta shrink-0">{formatDateTime(row.at)}</span>
          </li>
        ))}
      </ul>
    )}
    <Link to="/ai/activity" className="field-label text-[var(--stamp)] hover:underline inline-block mt-2">All activity ›</Link>
  </Sheet>
);

const Today = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [autopilotOn, setAutopilotOn] = useState(false);

  const load = () => {
    api.get(endpoints.today).then((res) => { setData(res.data); setAutopilotOn(res.data.live_armed?.autopilot || false); })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load today.'));
    api.get(endpoints.settings.preferences).then((res) => setAutopilotOn(!!res.data.autopilot_enabled)).catch(() => {});
  };
  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, []);

  const stop = () => api.put(endpoints.settings.preferences, { autopilot_enabled: false }).then(() => setAutopilotOn(false));

  if (!data) {
    return (
      <Layout>
        <div className="max-w-3xl">{error ? <Sheet title="Today"><p className="text-sm">{error}</p></Sheet> : <Sheet title="Today"><Ruling rows={5} /></Sheet>}</div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="private space-y-3 sm:space-y-4 max-w-3xl">
        <StatusStrip data={data} />
        <SetupChecklist setup={data.setup} />
        <NeedsYou items={data.needs_you || []} />
        <PnlSplit pnl={data.pnl_today} market={data.market} />
        <AiActivity rows={data.ai_activity} onStop={stop} autopilotOn={autopilotOn} />
        <Link to="/research" className="flex items-center justify-between gap-3 sheet px-3 py-2.5 sm:px-4 hover:bg-[var(--paper-sunk)]">
          <span className="text-sm"><span className="field-label">Markets</span> · NIFTY, BANK NIFTY, movers and news</span>
          <ArrowRight className="w-4 h-4 text-[var(--ink-faint)]" />
        </Link>
      </div>
    </Layout>
  );
};

export default Today;
