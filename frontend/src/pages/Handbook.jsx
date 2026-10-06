import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import Markdown from '../components/common/Markdown';
import SystemTabs from '../components/system/SystemTabs';
import LivePanel from '../components/system/LivePanels';
import { useTab } from '../hooks/useTab';
import { HANDBOOK_TABS, PANELS, splitLive } from '../utils/handbook';
import api, { endpoints } from '../utils/api';
import system from '../handbook/system-and-data.md?raw';
import trading from '../handbook/trading-and-money.md?raw';
import ai from '../handbook/ai-and-news.md?raw';
import ops from '../handbook/jobs-and-ops.md?raw';
import journey from '../handbook/journey.md?raw';

/**
 * The operator's handbook (admin-only): how NeoTrade works, written in
 * src/handbook/*.md, with live panels from GET /system/status where the
 * markdown marks them.
 */
const DOCS = { system, trading, ai, ops, journey };

const Handbook = () => {
  const [tab, setTab] = useTab(HANDBOOK_TABS.map((t) => t.id));
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let live = true;
    const load = () =>
      api.get(endpoints.system.status)
        .then((res) => live && setStatus(res.data))
        .catch((err) => live && setStatus({ as_of: new Date().toISOString(), error: err?.response?.data?.detail || 'Could not read status' }));
    const onShow = () => document.visibilityState === 'visible' && load();
    load();
    document.addEventListener('visibilitychange', onShow);
    return () => {
      live = false;
      document.removeEventListener('visibilitychange', onShow);
    };
  }, []);

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SystemTabs active={tab} onSelect={setTab} />
        <article className="sheet px-3 py-3 sm:px-5 sm:py-4 text-sm leading-relaxed">
          {splitLive(DOCS[tab], PANELS).map((part, index) =>
            part.live ? <LivePanel key={part.live} name={part.live} status={status} /> : <Markdown key={index}>{part.md}</Markdown>
          )}
        </article>
      </div>
    </Layout>
  );
};

export default Handbook;
