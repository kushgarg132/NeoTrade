import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Stat from '../components/ui/Stat';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Empty from '../components/ui/Empty';
import Button from '../components/ui/Button';
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
  return (
    <Layout>
      <PageHeader title="Money" />
      <div className="space-y-4">
        <Card>
          {error ? (
            <ErrorLine message={error} onRetry={load} />
          ) : !overview ? (
            <Skeleton rows={3} />
          ) : !h ? (
            <Empty
              title="Nothing here yet"
              body="Connect your broker, or import your trades and mutual funds from files."
              action={<Button onClick={() => setTab('holdings')}>Import files</Button>}
            />
          ) : (
            <>
              <div className="text-[13px] text-[var(--text-muted)]">Your money</div>
              <div className="private figure-lg text-[32px] leading-10 font-bold tabular-nums text-[var(--text)]">{inr(h.value)}</div>
              <div className="grid grid-cols-2 gap-4 mt-3">
                <Stat
                  label="Today"
                  value={inr(h.day_change, { sign: true })}
                  delta={pct(h.day_change_pct / 100, { sign: true })}
                  tone={tone(h.day_change)}
                />
                <Stat label="Yearly return (XIRR)" value={formatXirr(h.xirr)} delta={`NIFTY ${formatXirr(h.nifty_xirr)}`} />
              </div>
              <p className="text-[13px] text-[var(--text-muted)] mt-3">
                {holdingsStale(h.holdings_as_of)
                  ? `Holdings as of ${formatDateTime(h.holdings_as_of)}. Broker logged out.`
                  : 'NIFTY: the same rupees put in on the same days.'}
              </p>
            </>
          )}
        </Card>

        <Tabs tabs={TABS} value={tab} onChange={setTab} label="Money sections" />

        {tab === 'overview' && <OverviewTab headline={h} />}
        {tab === 'holdings' && <HoldingsTab />}
        {tab === 'tax' && <TaxTab onImport={() => setTab('holdings')} />}
        {tab === 'journal' && <JournalTab onImport={() => setTab('holdings')} />}
      </div>
    </Layout>
  );
};

export default Money;
