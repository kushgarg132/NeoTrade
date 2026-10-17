import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { X } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { MINE_TABS } from '../components/layout/sections';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, StockIcon } from '../components/doc/Doc';
import VerdictStamp from '../components/mine/VerdictStamp';
import Rebalance from '../components/portfolio/Rebalance';
import OrderTicket from '../components/trading/OrderTicket';
import NewsChip from '../components/common/NewsChip';
import useSymbolNews from '../hooks/useSymbolNews';
import api, { endpoints } from '../utils/api';
import { useRefetchOn } from '../hooks/useStream';
import { sortHoldings, targetProgress } from '../utils/mine';
import { formatCurrency, formatPercent, formatDateTime, marketPhase } from '../utils/formatters';
import { cn } from '../utils/cn';

const LIVE_POLL_MS = 5_000;
const SORTS = [['weight', 'Weight'], ['day', 'Day'], ['gain', 'Gain'], ['verdict', 'Verdict']];
const FILTERS = [['needs', 'Needs you'], ['STOCK', 'Stocks'], ['FUND', 'Funds']];

const CHIP =
  'min-h-9 px-2.5 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em]';
const Chip = ({ on, onClick, children }) => (
  <button
    type="button"
    aria-pressed={on}
    onClick={onClick}
    className={cn(CHIP, on ? 'border-[var(--ink)] text-[var(--ink)]' : 'border-[var(--rule-strong)] text-[var(--ink-faint)]')}
  >
    {children}
  </button>
);

const dayPct = (r) => (r.last_price && r.close_price ? ((r.last_price - r.close_price) / r.close_price) * 100 : null);

const Progress = ({ row }) => {
  const p = targetProgress(row.avg_price, row.last_price ?? row.close_price, row.thesis_target);
  if (p == null) return null;
  return (
    <span className="block h-1 bg-[var(--rule)] mt-1" role="img" aria-label={`${Math.round(p * 100)}% of the way to your target`}>
      <span className="block h-full bg-[var(--ink)]" style={{ width: `${p * 100}%` }} />
    </span>
  );
};

/** Mine → Holdings: every position, sortable, each leading to its stock page. */
const MineHoldings = () => {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actions, setActions] = useState([]);
  const [sort, setSort] = useState('weight');
  const [filters, setFilters] = useState([]);
  const [ticket, setTicket] = useState(null);
  const [reading, setReading] = useState(null);
  const plan = params.get('plan') === '1';

  // A failed poll keeps what is on screen.
  const load = useCallback(
    (stale = () => false) =>
      api
        .get(endpoints.portfolio.get, { params: { account: 'mine', live: true } })
        .then((res) => !stale() && setSnapshot(res.data))
        .catch(() => {})
        .finally(() => !stale() && setLoading(false)),
    []
  );
  useEffect(() => {
    let gone = false;
    let inFlight = false;
    const fetchLive = () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      load(() => gone).finally(() => { inFlight = false; });
    };
    fetchLive();
    // Every 5s while NSE trades; fresh again the moment the tab is shown.
    const timer = setInterval(() => marketPhase() !== 'closed' && fetchLive(), LIVE_POLL_MS);
    document.addEventListener('visibilitychange', fetchLive);
    return () => {
      gone = true;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', fetchLive);
    };
  }, [load]);
  useRefetchOn(['portfolio', 'trades'], () => load());
  useEffect(() => {
    api.get(endpoints.mine.actions).then((res) => setActions(res.data)).catch(() => setActions([]));
  }, []);

  const all = useMemo(() => snapshot?.holdings || [], [snapshot]);
  const { news } = useSymbolNews(all.filter((r) => r.kind === 'STOCK').map((r) => r.symbol));
  const rows = useMemo(() => {
    const needs = new Set(actions.map((a) => a.symbol));
    const kinds = filters.filter((f) => f !== 'needs');
    return sortHoldings(
      all
        .filter((r) => !filters.includes('needs') || needs.has(r.symbol))
        .filter((r) => !kinds.length || kinds.includes(r.kind === 'STOCK' ? 'STOCK' : 'FUND'))
        .map((r) => ({ ...r, day_change_pct: dayPct(r) })),
      sort
    );
  }, [all, actions, filters, sort]);
  // Before the first daily review there is no snapshot (GET /portfolio is 404): read it now.
  const readNow = () => {
    setReading('busy');
    api.post(endpoints.portfolio.refresh)
      .then(() => { setReading(null); return load(); })
      .catch((err) => setReading(err?.response?.data?.detail || 'Could not read your holdings.'));
  };
  const toggle = (f) => setFilters((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));
  const open = (r) => r.kind !== 'MF' && navigate(`/mine/stock/${encodeURIComponent(r.symbol)}`);
  const closePlan = () => setParams({}, { replace: true });
  const asOf = snapshot?.holdings_as_of || snapshot?.stale_since;

  const planButton = (
    <button type="button" className={cn(CHIP, 'border-[var(--ink)] text-[var(--ink)]')} onClick={() => setParams({ plan: '1' })}>
      Plan new money
    </button>
  );

  return (
    <Layout>
      <div className="private space-y-3 sm:space-y-4">
        <SectionTabs tabs={MINE_TABS} label="My account" />
        <Sheet
          title="Holdings"
          meta={snapshot ? (asOf ? `Holdings as of ${formatDateTime(asOf)} · broker logged out` : `${all.length} · ${formatDateTime(snapshot.at)}`) : null}
          actions={snapshot ? planButton : null}
        >
          {loading ? (
            <Ruling rows={4} />
          ) : !snapshot ? (
            <Empty
              title="No holdings yet"
              detail={reading && reading !== 'busy' ? reading : 'Connect your broker in Settings, then read your holdings.'}
              action={
                <button type="button" onClick={readNow} disabled={reading === 'busy'} className={cn(CHIP, 'border-[var(--ink)] text-[var(--ink)]')}>
                  {reading === 'busy' ? 'Reading…' : 'Read holdings now'}
                </button>
              }
            />
          ) : (
            <>
              {asOf && (
                <p className="doc-meta normal-case pb-2">
                  Your broker is logged out: priced from market quotes. Log in to your broker to refresh the list.
                </p>
              )}
              <div className="flex flex-wrap gap-1 pb-1" role="group" aria-label="Sort by">
                {SORTS.map(([id, label]) => <Chip key={id} on={sort === id} onClick={() => setSort(id)}>{label}</Chip>)}
              </div>
              <div className="flex flex-wrap gap-1 pb-2" role="group" aria-label="Filter">
                {FILTERS.map(([id, label]) => <Chip key={id} on={filters.includes(id)} onClick={() => toggle(id)}>{label}</Chip>)}
              </div>
              {rows.length === 0 ? (
                <Empty title="Nothing matches" detail="Clear a filter to see the rest." />
              ) : (
                <>
                  <ul className="sm:hidden -mx-3 divide-y divide-[var(--rule)]">
                    {rows.map((r) => (
                      <li key={r.isin || r.symbol}>
                        <button type="button" onClick={() => open(r)} className="w-full px-3 py-2.5 flex items-center gap-3 text-left hover:bg-[var(--paper-sunk)]">
                          <span className="min-w-0 flex-1">
                            <span className="figure-md text-sm flex items-center gap-1.5 min-w-0">
                              {r.kind !== 'MF' && <StockIcon symbol={r.symbol} />}
                              <span className="truncate">{r.kind === 'MF' ? r.name || r.symbol : r.symbol}</span>
                            </span>
                            <span className="doc-meta normal-case block truncate">
                              {r.weight_pct != null ? formatPercent(r.weight_pct) : r.kind}
                              {r.day_change_pct != null && <> · day <Money value={r.day_change_pct} percent size="sm" className="text-xs" /></>}
                            </span>
                            <NewsChip entry={news?.[r.symbol]} link={false} />
                            <Progress row={r} />
                          </span>
                          <span className="text-right shrink-0">
                            <span className="figure-md text-sm block">{r.value != null ? formatCurrency(r.value) : '—'}</span>
                            <Money value={r.pnl_pct} percent size="sm" className="text-xs" />
                          </span>
                          <span className="w-[4.5rem] flex justify-end shrink-0"><VerdictStamp verdict={r.verdict} compact /></span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <div className="hidden sm:block">
                    <Statement
                      columns={[
                        { key: 'scrip', label: 'Holding' },
                        { key: 'weight', label: 'Weight', align: 'right' },
                        { key: 'value', label: 'Value', align: 'right' },
                        { key: 'day', label: 'Day', align: 'right' },
                        { key: 'gain', label: 'Gain', align: 'right' },
                        { key: 'target', label: 'To target', align: 'right' },
                        { key: 'verdict', label: 'Review', align: 'right' },
                      ]}
                    >
                      {rows.map((r) => (
                        <Row key={r.isin || r.symbol} className="cursor-pointer hover:bg-[var(--paper-sunk)]" onClick={() => open(r)}>
                          <Cell>
                            {r.kind === 'MF' ? <span className="text-sm">{r.name || r.symbol}</span> : <span className="figure-md text-sm">{r.symbol}</span>}
                            <NewsChip entry={news?.[r.symbol]} link={false} />
                          </Cell>
                          <Cell align="right" mono>{r.weight_pct != null ? formatPercent(r.weight_pct) : '—'}</Cell>
                          <Cell align="right" mono>{r.value != null ? formatCurrency(r.value) : '—'}</Cell>
                          <Cell align="right">{r.day_change_pct != null ? <Money value={r.day_change_pct} percent /> : <span className="doc-meta">—</span>}</Cell>
                          <Cell align="right">{r.pnl_pct != null ? <Money value={r.pnl_pct} percent /> : <span className="doc-meta">—</span>}</Cell>
                          <Cell align="right">{r.thesis_target != null ? <span className="inline-block w-24"><Progress row={r} /></span> : <span className="doc-meta">—</span>}</Cell>
                          <Cell align="right"><VerdictStamp verdict={r.verdict} /></Cell>
                        </Row>
                      ))}
                    </Statement>
                  </div>
                </>
              )}
            </>
          )}
        </Sheet>
      </div>

      {plan && snapshot && (
        <div className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/40" onClick={closePlan}>
          <div
            role="dialog"
            aria-label="Plan new money"
            className="bg-[var(--paper)] w-full sm:max-w-3xl max-h-[90vh] overflow-y-auto p-3 sm:p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-end">
              <button type="button" onClick={closePlan} aria-label="Close" className="min-h-9 min-w-9 inline-flex items-center justify-center text-[var(--ink-faint)] hover:text-[var(--ink)]">
                <X className="w-4 h-4" />
              </button>
            </div>
            <Rebalance snapshot={snapshot} onTrade={(t) => { closePlan(); setTicket(t); }} />
          </div>
        </div>
      )}
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} />}
    </Layout>
  );
};

export default MineHoldings;
