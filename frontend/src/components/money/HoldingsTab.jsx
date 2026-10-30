import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { X, ArrowDown, Plus, Pause, AlertTriangle } from 'lucide-react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';
import ListRow from '../ui/ListRow';
import { inr, pct } from '../ui/format';
import { toneText } from '../ui/tone';
import ImportFiles from './ImportFiles';
import useHoldings from './useHoldings';
import Rebalance from '../portfolio/Rebalance';
import OrderTicket from '../trading/OrderTicket';
import useSymbolNews from '../../hooks/useSymbolNews';
import { ImpactChips } from '../common/NewsImpacts';
import api, { endpoints } from '../../utils/api';
import { sortHoldings, whyLine, dayFraction, allocation, MARKET_WHY } from '../../utils/money';
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

const SORTS = [['value', 'Value'], ['day', 'Today'], ['pnl', 'P&L'], ['weight', 'Weight']];
// Each verdict gets its own colour + icon, so Sell / Add / Hold read at a glance (icon covers colour-blind).
const VERDICT = {
  SELL: { label: 'Sell', Icon: ArrowDown, pill: 'bg-[var(--loss-soft)] text-[var(--loss)]', on: 'bg-[var(--loss)]' },
  ADD: { label: 'Add', Icon: Plus, pill: 'bg-[var(--gain-soft)] text-[var(--gain)]', on: 'bg-[var(--gain)]' },
  REVIEW: { label: 'Review first', Icon: AlertTriangle, pill: 'bg-[color-mix(in_oklab,var(--warn)_14%,var(--surface))] text-[var(--warn)]', on: 'bg-[var(--warn)]' },
  HOLD: { label: 'Hold', Icon: Pause, pill: 'bg-[var(--surface-2)] text-[var(--text-muted)]', on: 'bg-[var(--text-muted)]' },
  KEEP: { label: 'Keep', Icon: Pause, pill: 'bg-[var(--surface-2)] text-[var(--text-muted)]', on: 'bg-[var(--text-muted)]' },
};
const VERDICT_ORDER = ['SELL', 'REVIEW', 'ADD', 'HOLD', 'KEEP'];

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
      on ? `${onCls} text-[var(--accent-ink)] border-transparent` : `bg-[var(--surface)] ${offCls} border-[var(--border)]`
    )}
  >
    {children}
  </button>
);

/** One holding in two lines: name and value, then quantity and weight beside its gain and today's move; then its
 *  verdict and why, and its news analysis. A fund has no stock page, so it is not a link. */
const Row = ({ h, news }) => {
  const day = h.day_pct;
  const why = whyLine({ ...h, news });
  const mf = h.kind === 'MF';
  const body = (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="min-w-0 break-words text-[15px] font-bold text-[var(--text)]">{mf ? h.name || h.symbol : h.symbol}</span>
          {!mf && <NewsDot entry={news} />}
          {!mf && newsToday(news) && <Badge kind={newsTone(news) === 'neg' ? 'alert' : 'neutral'}>News</Badge>}
        </span>
        <span className="private shrink-0 text-[15px] font-semibold tabular-nums text-[var(--text)]">{h.value != null ? inr(h.value) : '—'}</span>
      </div>
      <div className="mt-0.5 flex items-baseline justify-between gap-3 text-[13px] tabular-nums">
        <span className="min-w-0 truncate text-[var(--text-muted)]">
          <span className="private">{formatQuantity(h.quantity)}</span>{h.last_price != null && <> @ {inr(h.last_price)}</>}{h.weight_pct != null && <> · <span className="private">{h.weight_pct.toFixed(1)}%</span></>}
        </span>
        <span className="shrink-0 whitespace-nowrap">
          <span className={`private font-semibold ${toneText(tone(h.pnl))}`}>{h.pnl != null ? inr(h.pnl, { sign: true }) : '—'}</span>
          {h.pnl_pct != null && <span className={toneText(tone(h.pnl))}> {pct(h.pnl_pct / 100, { sign: true, dp: 1 })}</span>}
          {day != null && <span className="text-[var(--text-muted)]"> · today <span className={toneText(tone(day))}>{pct(day, { sign: true })}</span></span>}
        </span>
      </div>
      {(h.verdict || why !== MARKET_WHY) && (
        <div className="mt-1.5 flex items-center gap-2 min-w-0">
          {h.verdict && <VerdictPill v={h.verdict} />}
          {why !== MARKET_WHY && <span className="min-w-0 truncate text-[12px] text-[var(--text-muted)]">{why}</span>}
        </div>
      )}
      {news?.headline && <ImpactChips impacts={news.impacts} className="mt-1" />}
    </>
  );
  const cls = 'block py-3 border-b border-[var(--border)] last:border-b-0';
  return mf ? <div className={cls}>{body}</div> : <Link to={stockPath(h.symbol)} className={`${cls} tap -mx-2 px-2 hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`}>{body}</Link>;
};

/** Where the money sits: the largest holdings as one stacked bar, with a legend. */
const Allocation = ({ rows }) => {
  const parts = allocation(rows);
  if (parts.length < 2) return null;
  const color = (i, last) => (last && parts.length > 6 ? 'var(--surface-2)' : `var(--chart-${(i % 6) + 1})`);
  return (
    <div className="mb-4">
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label={parts.map((p) => `${p.label} ${p.pct.toFixed(0)}%`).join(', ')}>
        {parts.map((p, i) => <span key={p.label} style={{ width: `${p.pct}%`, background: color(i, i === parts.length - 1) }} />)}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] tabular-nums text-[var(--text-muted)]">
        {parts.map((p, i) => (
          <span key={p.label} className="inline-flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{ background: color(i, i === parts.length - 1) }} aria-hidden="true" />
            <span className="max-w-[9rem] truncate">{p.label}</span> <span className="private">{p.pct.toFixed(0)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
};

const HoldingsTab = () => {
  const [params, setParams] = useSearchParams();
  const { snapshot, loading, error, reload } = useHoldings({ poll: true });
  const [sort, setSort] = useState('value');
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
                <Link to="/settings/brokers" className="inline-flex items-center justify-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold">Connect your broker</Link>
                <Button variant="secondary" onClick={readNow} disabled={reading === 'busy'}>{reading === 'busy' ? 'Reading…' : 'Read holdings now'}</Button>
                <Button variant="secondary" onClick={() => setImporting(true)}>Import files</Button>
              </span>
            }
          />
        ) : (
          <>
            <p className="text-[13px] text-[var(--text-muted)] mb-3">
              {asOf ? `Holdings as of ${formatDateTime(asOf)}. Broker logged out: priced from market quotes.` : `${all.length} holdings · ${formatDateTime(snapshot.at)}`}
            </p>
            <Allocation rows={all} />
            <div className="mb-2 flex items-center gap-2">
              <label className="shrink-0 inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)]">
                Sort
                <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort holdings by"
                  className="min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface-2)] px-2.5 text-[14px] font-medium text-[var(--text)]">
                  {SORTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                </select>
              </label>
              <div className="-mr-4 flex min-w-0 flex-1 gap-2 overflow-x-auto pr-4" role="group" aria-label="Show">
                <Chip on={needsOnly} onClick={() => setNeedsOnly((v) => !v)}>Needs you</Chip>
                <Chip on={newsOnly} onClick={() => setNewsOnly((v) => !v)}>Has news</Chip>
                {VERDICT_ORDER.filter((v) => counts[v]).map((v) => {
                  const { label, Icon, on, pill } = VERDICT[v];
                  return (
                    <Chip key={v} on={verdict === v} onCls={on} offCls={pill.split(' ')[1]} onClick={() => setVerdict((cur) => (cur === v ? null : v))}>
                      <span className="inline-flex items-center gap-1 whitespace-nowrap"><Icon className="w-3.5 h-3.5" aria-hidden="true" />{label} · {counts[v]}</span>
                    </Chip>
                  );
                })}
              </div>
            </div>
            {rows.length === 0 ? (
              <Empty title="Nothing matches" body="Clear the filter to see the rest." />
            ) : (
              <div>{rows.map((h) => <Row key={h.isin || h.symbol} h={h} news={news?.[h.symbol]} />)}</div>
            )}
          </>
        )}
      </Card>

      <Card>
        <ListRow title="Import trades or funds" sub="Zerodha tradebook CSV, CAMS or KFintech statement" onClick={() => setImporting(true)} />
      </Card>
      {importing && (
        <div className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/40" onClick={() => setImporting(false)}>
          <div role="dialog" aria-label="Import trades or funds" className="bg-[var(--bg)] w-full sm:max-w-xl max-h-[90vh] overflow-y-auto p-3 sm:p-4 rounded-t-[20px] sm:rounded-[20px]" onClick={(e) => e.stopPropagation()}>
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
            className="bg-[var(--bg)] w-full sm:max-w-3xl max-h-[90vh] overflow-y-auto p-3 sm:p-4 rounded-t-[20px] sm:rounded-[20px]"
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
