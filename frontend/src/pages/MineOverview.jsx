import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { PORTFOLIO_TABS } from '../components/layout/sections';
import { stockPath } from '../utils/stocks';
import { Sheet, Money, Empty, Ruling, Scrip } from '../components/doc/Doc';
import WaitingCards from '../components/decisions/WaitingCards';
import ValueCurve from '../components/mine/ValueCurve';
import NeedsYou from '../components/mine/NeedsYou';
import Mix from '../components/mine/Mix';
import api, { endpoints } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { formatCurrency, formatDateTime } from '../utils/formatters';
import { formatXirr, holdingsStale } from '../utils/mine';
import { cn } from '../utils/cn';

const Drivers = ({ drivers }) => {
  const [span, setSpan] = useState('month');
  const d = drivers?.[span] || { top: [], bottom: [] };
  const toggle = (
    <div className="flex gap-1" role="group" aria-label="Period">
      {[['month', 'This month'], ['all', 'All time']].map(([id, label]) => (
        <button
          key={id}
          type="button"
          aria-pressed={span === id}
          onClick={() => setSpan(id)}
          className={cn(
            'min-h-9 px-2.5 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em]',
            span === id ? 'border-[var(--ink)] text-[var(--ink)]' : 'border-[var(--rule-strong)] text-[var(--ink-faint)]'
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
  const list = (title, rows) => (
    <div>
      <p className="field-label mb-1">{title}</p>
      {rows.length === 0 ? (
        <p className="text-sm text-[var(--ink-faint)]">—</p>
      ) : (
        <ul>
          {rows.map((r) => (
            <li key={r.symbol} className="flex items-center justify-between py-1.5 border-b border-[var(--rule)]">
              <Link to={stockPath(r.symbol)} className="hover:text-[var(--stamp)]">
                <Scrip symbol={r.symbol} />
              </Link>
              <Money value={r.contribution} size="sm" className="text-sm" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
  return (
    <Sheet title="What drove it" actions={toggle}>
      <div className="grid sm:grid-cols-2 gap-x-6 gap-y-4">
        {list('Added most', d.top)}
        {list('Cost most', d.bottom)}
      </div>
    </Sheet>
  );
};

/** Mine → Overview: where the account stands and what needs you. */
const MineOverview = () => {
  const [overview, setOverview] = useState(null);
  const [actions, setActions] = useState([]);
  const [actionsFailed, setActionsFailed] = useState(false);
  const [error, setError] = useState(null);

  const loadActions = useCallback(
    () =>
      api
        .get(endpoints.mine.actions)
        .then((res) => (setActions(res.data), setActionsFailed(false)))
        .catch(() => setActionsFailed(true)),
    []
  );
  const load = useCallback(() => {
    api
      .get(endpoints.mine.overview)
      .then((res) => (setOverview(res.data), setError(null)))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load your account'));
    loadActions();
  }, [loadActions]);
  useEffect(load, [load]);
  useReconnect(load);
  useTopic('suggestions', loadActions);

  const h = overview?.headline;
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4">
        <SectionTabs tabs={PORTFOLIO_TABS} label="Portfolio" />

        <Sheet title="Your account" meta={holdingsStale(h?.holdings_as_of) ? `Holdings as of ${formatDateTime(h.holdings_as_of)} · broker logged out` : h?.as_of ? formatDateTime(h.as_of) : null}>
          {error ? (
            <Empty title="Could not load" detail={error} />
          ) : !overview ? (
            <Ruling rows={3} />
          ) : !h ? (
            <Empty
              title="Nothing here yet"
              detail="Connect your broker, or import your trades and mutual funds from files."
              action={<Link to="/portfolio/import" className="field-label text-[var(--stamp)] hover:underline min-h-11 inline-flex items-center">Import files ›</Link>}
            />
          ) : (
            <>
              <p className="figure-lg text-[clamp(1.75rem,8vw,2.5rem)]">{formatCurrency(h.value)}</p>
              <dl className="grid grid-cols-3 gap-x-3 mt-3">
                <div>
                  <dt className="field-label">Today</dt>
                  <dd><Money value={h.day_change} size="sm" className="text-sm" /></dd>
                  <dd><Money value={h.day_change_pct} percent size="sm" className="text-xs" /></dd>
                </div>
                <div>
                  <dt className="field-label">Total gain</dt>
                  <dd><Money value={h.pnl} size="sm" className="text-sm" /></dd>
                  <dd><Money value={h.pnl_pct} percent size="sm" className="text-xs" /></dd>
                </div>
                <div>
                  <dt className="field-label">XIRR</dt>
                  <dd className="figure-md text-sm">{formatXirr(h.xirr)}</dd>
                  <dd className="doc-meta normal-case">NIFTY {formatXirr(h.nifty_xirr)}</dd>
                </div>
              </dl>
              <p className="doc-meta normal-case mt-2">NIFTY: the same rupees in on the same days.</p>
            </>
          )}
        </Sheet>

        <ValueCurve />
        <WaitingCards />
        {actionsFailed ? (
          <Sheet title="Needs you"><Empty title="Couldn't load" detail="Try again in a moment." /></Sheet>
        ) : (
          <NeedsYou actions={actions} onChanged={load} />
        )}
        {overview?.drivers && <Drivers drivers={overview.drivers} />}
        {overview?.mix && <Mix concentration={overview.mix} count={overview.mix.count ?? 0} />}
      </div>
    </Layout>
  );
};

export default MineOverview;
