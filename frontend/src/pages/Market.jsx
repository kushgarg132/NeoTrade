import React from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Pulse from '../components/market/Pulse';
import Watchlist from '../components/market/Watchlist';
import News from '../components/market/News';

const TABS = [
  { id: 'pulse', label: 'Pulse' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'news', label: 'News' },
];

const Market = () => {
  const [tab, setTab] = useTabParam(TABS.map((t) => t.id));
  return (
    <Layout>
      <PageHeader title="Market" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Market sections" />
      <div className="pt-3">
        {tab === 'pulse' && <Pulse />}
        {tab === 'watchlist' && <Watchlist />}
        {tab === 'news' && <News />}
      </div>
    </Layout>
  );
};

export default Market;
