import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { X, ArrowDown, Plus, Pause, AlertTriangle } from 'lucide-react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';
import ListRow from '../ui/ListRow';
import { inr, pct, compactInr } from '../ui/format';
import { toneText } from '../ui/tone';
import ImportFiles from './ImportFiles';
import useHoldings from './useHoldings';
import Rebalance from '../portfolio/Rebalance';
import OrderTicket from '../trading/OrderTicket';
import useSymbolNews from '../../hooks/useSymbolNews';
import api, { endpoints } from '../../utils/api';
import { sortHoldings, whyLine, dayFraction, MARKET_WHY } from '../../utils/money';
import { stockPath } from '../../utils/stocks';
import { formatDateTime, formatQuantity } from '../../utils/formatters';
import { cn } from '../../utils/cn';
import Badge from '../ui/Badge';
import { hasNews, newsToday, tone as newsTone } from '../../utils/news';

// Sentiment dot beside the symbol: colour plus a screen-reader word (the "News" badge and why-line carry the text).
const DOT = { pos: ['bg-[var(--gain)]', 'news positive'], neg: ['bg-[var(--loss)]', 'news negative'] };
const NewsDot = ({ entry }) => {
  const d = DOT[newsTone(entry)];
  return d ? <span role="img" aria-label={d[1]} title={d[1]} className={`inline-block w-2 h-2 shrink-0 rounded-full ${d[0]}`} /> : null;
};

const SORTS = [['day', 'Today'], ['value', 'Value'], ['weight', 'Weight'], ['pnl', 'P&L']];
// Each verdict gets its own colour + icon, so Sell / Add / Hold read at a glance (icon covers colour-blind).
const VERDICT = {
  SELL: { label: 'Sell', Icon: ArrowDown, pill: 'bg-[var(--loss-wash)] text-[var(--loss)]', stripe: 'border-l-[var(--loss)]', on: 'bg-[var(--loss)]' },
  ADD: { label: 'Add', Icon: Plus, pill: 'bg-[var(--gain-wash)] text-[var(--gain)]', stripe: 'border-l-[var(--gain)]', on: 'bg-[var(--gain)]' },
  REVIEW: { label: 'Review first', Icon: AlertTriangle, pill: 'bg-[color-mix(in_oklab,var(--warn)_14%,var(--surface))] text-[var(--warn)]', stripe: 'border-l-[var(--warn)]', on: 'bg-[var(--warn)]' },
  HOLD: { label: 'Hold', Icon: Pause, pill: 'bg-[var(--surface-2)] text-[var(--text-muted)]', stripe: 'border-l-transparent', on: 'bg-[var(--text-muted)]' },
};
const VERDICT_ORDER = ['SELL', 'REVIEW', 'ADD', 'HOLD'];

const VerdictPill = ({ v }) => {
  const s = VERDICT[v];
  if (!s) return <div className="text-[12px] font-semibold text-[var(--text)]">{v}</div>;
  return (
    <span className={`mt-0.5 inline-flex items-center gap-1 rounded-full px-2 min-h-6 text-[12px] font-semibold ${s.pill}`}>
      <s.Icon className="w-3 h-3" aria-hidden="true" />{s.label}
    </span>
  );
};
const tone = (x) => (x > 0 ? 'gain' : x < 0 ? 'loss' : 'neutral');

const Chip = ({ on, onClick, children, onCls = 'bg-[var(--accent)]', offCls = 'text-[var(--text-muted)]' }) => (
  <button
    type="button"
    aria-pressed={on}
    onClick={onClick}
    className={cn(
      'min-h-11 px-3 shrink-0 rounded-full text-[14px] font-medium border',
      on ? `${onCls} text-[var(--surface)] border-transparent` : `bg-[var(--surface)] ${offCls} border-[var(--border)]`
    )}
  >
    {children}
  </button>
);

const Cell = ({ top, sub, topCls = 'text-[var(--text)]', subCls = 'text-[var(--text-muted)]' }) => (
  <div className="text-right tabular-nums min-w-0">
    <div className={`text-[14px] font-medium ${topCls}`}>{top}</div>
    <div className={`text-[12px] ${subCls}`}>{sub}</div>
  </div>
);

// symbol+qty | LTP, today % | P&L rupees, % | weight, value
const COLS = 'grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,0.8fr)] gap-x-2 items-center';

const Head = () => (
  <div className={`${COLS} text-[12px] text-[var(--text-muted)] pb-1 border-b border-[var(--border)]`} aria-hidden="true">
    <span>Stock · qty</span><span className="text-right">LTP · today</span><span className="text-right">P&amp;L</span><span className="text-right">Weight</span>
  </div>
);

const Row = ({ h, news }) => {
  const day = h.day_pct;
  const why = whyLine({ ...h, news });
  const mf = h.kind === 'MF';
  const body = (
    <>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-1.5 text-[15px] font-semibold text-[var(--text)] break-words">
          <span className="min-w-0">{mf ? h.name || h.symbol : h.symbol}</span>
          {!mf && <NewsDot entry={news} />}
          {!mf && newsToday(news) && <Badge kind={newsTone(news) === 'neg' ? 'alert' : 'neutral'}>News</Badge>}
        </div>
        <div className="text-[12px] text-[var(--text-muted)] tabular-nums truncate"><span className="private">{formatQuantity(h.quantity)}</span></div>
        {h.verdict && <VerdictPill v={h.verdict} />}
      </div>
      <Cell top={h.last_price != null ? inr(h.last_price) : '—'} sub={day != null ? pct(day, { sign: true }) : '—'} subCls={toneText(tone(day))} />
      <div className="private">
        <Cell
          top={h.pnl != null ? inr(h.pnl, { sign: true }) : '—'}
          topCls={toneText(tone(h.pnl))}
          sub={h.pnl_pct != null ? pct(h.pnl_pct / 100, { sign: true, dp: 1 }) : '—'}
          subCls={toneText(tone(h.pnl))}
        />
      </div>
      <div className="private">
        <Cell top={h.weight_pct != null ? `${h.weight_pct.toFixed(1)}%` : '—'} sub={h.value != null ? compactInr(h.value) : '—'} />
      </div>
      {why !== MARKET_WHY && <div className="col-span-4 text-[12px] text-[var(--text-muted)] truncate -mt-1">{why}</div>}
    </>
  );
  const stripe = VERDICT[h.verdict]?.stripe || 'border-l-transparent';
  const cls = `${COLS} gap-y-1 min-h-14 py-2 pl-2 border-l-[3px] ${stripe} border-b border-b-[var(--border)] last:border-b-0`;
  return mf ? <div className={cls}>{body}</div> : <Link to={stockPath(h.symbol)} className={`${cls} transition-colors hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`}>{body}</Link>;
};

const HoldingsTab = () => {
  const [params, setParams] = useSearchParams();
  const { snapshot, loading, error, reload } = useHoldings({ poll: true });
  const [sort, setSort] = useState('day');
  const [ticket, setTicket] = useState(null);
  const [importing, setImporting] = useState(false);
  const [reading, setReading] = useState(null);
  const [needsOnly, setNeedsOnly] = useState(false);
  const [newsOnly, setNewsOnly] = useState(false);
  const [verdict, setVerdict] = useState(null);
  const [needs, setNeeds] = useState(() => new Set());
  const plan = params.get('plan') === '1';

  useEffect(() => {
    api.get(endpoints.mine.actions).then((res) => setNeeds(new Set(res.data.map((a) => a.symbol)))).catch(() => {});
  }, []);

  const all = useMemo(() => snapshot?.holdings || [], [snapshot]);
  const { news } = useSymbolNews(all.filter((r) => r.kind === 'STOCK').map((r) => r.symbol));
  const counts = useMemo(() => all.reduce((m, r) => (r.verdict ? { ...m, [r.verdict]: (m[r.verdict] || 0) + 1 } : m), {}), [all]);
  const rows = useMemo(
    () => sortHoldings(all.filter((r) => (!needsOnly || needs.has(r.symbol)) && (!newsOnly || hasNews(news[r.symbol])) && (!verdict || r.verdict === verdict)).map((r) => ({ ...r, day_pct: dayFraction(r) })), sort),
    [all, needs, needsOnly, news, newsOnly, sort, verdict]
  );

  // Before the first daily review there is no snapshot (GET /portfolio is 404): read it now.
  const readNow = () => {
    setReading('busy');
    api.post(endpoints.portfolio.refresh)
      .then(() => { setReading(null); return reload(); })
      .catch((err) => setReading(err?.response?.data?.detail || 'Could not read your holdings.'));
  };
  const closePlan = () => setParams((p) => { const n = new URLSearchParams(p); n.delete('plan'); return n; }, { replace: true });
  const openPlan = () => setParams((p) => { const n = new URLSearchParams(p); n.set('plan', '1'); return n; }, { replace: true });
  const asOf = snapshot?.holdings_as_of || snapshot?.stale_since;

  return (
    <div className="space-y-4">
      <Card
        title="Holdings"
        action={snapshot ? <Button variant="secondary" className="min-h-11" onClick={openPlan}>Plan new money</Button> : null}
      >
        {loading ? (
          <Skeleton rows={4} />
        ) : error ? (
          <ErrorLine message="Couldn't load your holdings." onRetry={() => reload()} />
        ) : !snapshot || all.length === 0 ? (
          <Empty
            title="No holdings yet"
            body={reading && reading !== 'busy' ? reading : 'Connect your broker and read your holdings, or import your trades and funds from files.'}
            action={
              <span className="flex flex-wrap justify-center gap-2">
                <Link to="/settings?tab=accounts" className="inline-flex items-center justify-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold">Connect your broker</Link>
                <Button variant="secondary" onClick={readNow} disabled={reading === 'busy'}>{reading === 'busy' ? 'Reading…' : 'Read holdings now'}</Button>
                <Button variant="secondary" onClick={() => setImporting(true)}>Import files</Button>
              </span>
            }
          />
        ) : (
          <>
            <p className="text-[13px] text-[var(--text-muted)] mb-2">
              {asOf ? `Holdings as of ${formatDateTime(asOf)}. Broker logged out: priced from market quotes.` : `${all.length} holdings · ${formatDateTime(snapshot.at)}`}
            </p>
            <div className="flex gap-2 mb-2 overflow-x-auto" role="group" aria-label="Sort by">
              {SORTS.map(([id, label]) => <Chip key={id} on={sort === id} onClick={() => setSort(id)}>{label}</Chip>)}
              <Chip on={needsOnly} onClick={() => setNeedsOnly((v) => !v)}>Needs you</Chip>
              <Chip on={newsOnly} onClick={() => setNewsOnly((v) => !v)}>Has news</Chip>
            </div>
            {Object.keys(counts).length > 0 && (
              <div className="flex gap-2 mb-2 overflow-x-auto" role="group" aria-label="Show verdict">
                {VERDICT_ORDER.filter((v) => counts[v]).map((v) => {
                  const { label, Icon, on, pill } = VERDICT[v];
                  return (
                    <Chip key={v} on={verdict === v} onCls={on} offCls={pill.split(' ')[1]} onClick={() => setVerdict((cur) => (cur === v ? null : v))}>
                      <span className="inline-flex items-center gap-1"><Icon className="w-3.5 h-3.5" aria-hidden="true" />{label} · {counts[v]}</span>
                    </Chip>
                  );
                })}
              </div>
            )}
            {rows.length === 0 ? (
              <Empty title="Nothing matches" body="Clear the filter to see the rest." />
            ) : (
              <div><Head />{rows.map((h) => <Row key={h.isin || h.symbol} h={h} news={news?.[h.symbol]} />)}</div>
            )}
          </>
        )}
      </Card>

      <Card>
        <ListRow title="Import trades or funds" sub="Zerodha tradebook CSV, CAMS or KFintech statement" onClick={() => setImporting(true)} />
      </Card>
      {importing && (
        <div className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/40" onClick={() => setImporting(false)}>
          <div role="dialog" aria-label="Import trades or funds" className="bg-[var(--bg)] w-full sm:max-w-xl max-h-[90vh] overflow-y-auto p-3 sm:p-4 rounded-t-[16px] sm:rounded-[16px]" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-end">
              <button type="button" onClick={() => setImporting(false)} aria-label="Close" className="min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]">
                <X className="w-5 h-5" />
              </button>
            </div>
            <ImportFiles onImported={() => reload()} />
          </div>
        </div>
      )}

      {plan && snapshot && (
        <div className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/40" onClick={closePlan}>
          <div
            role="dialog"
            aria-label="Plan new money"
            className="bg-[var(--bg)] w-full sm:max-w-3xl max-h-[90vh] overflow-y-auto p-3 sm:p-4 rounded-t-[16px] sm:rounded-[16px]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-end">
              <button type="button" onClick={closePlan} aria-label="Close" className="min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]">
                <X className="w-5 h-5" />
              </button>
            </div>
            <Rebalance snapshot={snapshot} onTrade={(t) => { closePlan(); setTicket(t); }} />
          </div>
        </div>
      )}
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} />}
    </div>
  );
};

export default HoldingsTab;
