import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Hero from '../components/ui/Hero';
import DeltaChip from '../components/ui/DeltaChip';
import Stat from '../components/ui/Stat';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Empty from '../components/ui/Empty';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import { Link } from 'react-router-dom';
import { inr, pct, tone } from '../components/ui/format';
import OverviewTab from '../components/money/OverviewTab';
import HoldingsTab from '../components/money/HoldingsTab';
import TaxTab from '../components/money/TaxTab';
import JournalTab from '../components/money/JournalTab';
import api, { endpoints } from '../utils/api';
import { useReconnect } from '../hooks/useStream';
import { formatXirr, holdingsStale } from '../utils/mine';
import { formatDateTime } from '../utils/formatters';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'holdings', label: 'Holdings' },
  { id: 'tax', label: 'Tax' },
  { id: 'journal', label: 'Journal' },
];
const IDS = TABS.map((t) => t.id);

/** Money: what you own, what it did today and against NIFTY, then Holdings, Tax and Journal as tabs. */
const Money = () => {
  const [tab, setTab] = useTabParam(IDS);
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api
      .get(endpoints.mine.overview)
      .then((res) => (setOverview(res.data), setError(null)))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load your account.'));
  }, []);
  useEffect(load, [load]);
  useReconnect(load);

  const h = overview?.headline;
  const xirrAhead = typeof h?.xirr === 'number' && typeof h?.nifty_xirr === 'number' ? h.xirr - h.nifty_xirr : null;
  return (
    <Layout>
      <PageHeader title="Money" />
      <div className="space-y-4">
        {h ? (
          <Hero label="Your broker account" value={h.value} change={<DeltaChip value={h.day_change} pct={h.day_change_pct} suffix="today" />}>
            {holdingsStale(h.holdings_as_of) && (
              <div className="mt-3"><Badge kind="unproven">Stale · {formatDateTime(h.holdings_as_of)}</Badge></div>
            )}
            <div className="grid grid-cols-2 gap-3 mt-4 border-t border-[var(--border)] pt-3">
              <Stat label="Total P&L" value={inr(h.pnl, { sign: true })} delta={h.pnl_pct != null ? pct(h.pnl_pct / 100, { sign: true }) : '—'} tone={tone(h.pnl)} />
              <Stat label="Yearly (XIRR)" value={formatXirr(h.xirr)}
                delta={xirrAhead == null ? `NIFTY ${formatXirr(h.nifty_xirr)}` : `${xirrAhead >= 0 ? 'Ahead of' : 'Behind'} NIFTY ${formatXirr(h.nifty_xirr)}`}
                tone={xirrAhead == null ? 'neutral' : tone(xirrAhead)} />
            </div>
            <p className="text-[12px] text-[var(--text-muted)] mt-2">
              {holdingsStale(h.holdings_as_of)
                ? 'Broker logged out: these figures are not live.'
                : <>Put in <span className="private">{inr(h.value - h.pnl)}</span> · NIFTY = the same rupees on the same days</>}
            </p>
          </Hero>
        ) : (
          <Card>
            {error ? (
              <ErrorLine message={error} onRetry={load} />
            ) : !overview ? (
              <Skeleton rows={3} />
            ) : (
              <Empty
                title="Nothing here yet"
                body="Connect your broker and your holdings and trades come in on their own, or import your trades and mutual funds from files."
                action={
                  <span className="flex flex-wrap justify-center gap-2">
                    <Link to="/settings/brokers" className="inline-flex items-center justify-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold">Connect your broker</Link>
                    <Button variant="secondary" onClick={() => setTab('holdings')}>Import files</Button>
                  </span>
                }
              />
            )}
          </Card>
        )}

        <Tabs tabs={TABS} value={tab} onChange={setTab} label="Money sections" />

        {tab === 'overview' && <OverviewTab headline={h} overview={overview} />}
        {tab === 'holdings' && <HoldingsTab />}
        {tab === 'tax' && <TaxTab onImport={() => setTab('holdings')} />}
        {tab === 'journal' && <JournalTab onImport={() => setTab('holdings')} />}
      </div>
    </Layout>
  );
};

export default Money;
