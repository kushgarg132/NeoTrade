import React from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Today from '../components/market/Today';
import Sectors from '../components/market/Sectors';
import Watchlist from '../components/market/Watchlist';
import News from '../components/market/News';

const TABS = [
  { id: 'today', label: 'Today' },
  { id: 'sectors', label: 'Sectors' },
  { id: 'news', label: 'News' },
  { id: 'watchlist', label: 'Watchlist' },
];

const Market = () => {
  // ?tab=pulse is the retired tab: old links land on Today.
  const [tab, setTab] = useTabParam(TABS.map((t) => t.id), 'today', 'tab', (v) => (v === 'pulse' ? 'today' : v));
  return (
    <Layout>
      <PageHeader title="Market" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Market sections" />
      <div className="pt-3">
        {tab === 'today' && <Today />}
        {tab === 'sectors' && <Sectors />}
        {tab === 'news' && <News />}
        {tab === 'watchlist' && <Watchlist />}
      </div>
    </Layout>
  );
};

export default Market;
