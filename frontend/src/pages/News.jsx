import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import { Sheet, Tabs, Empty, Ruling } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { useReconnect, useTopic } from '../hooks/useStream';
import { cn } from '../utils/cn';
import { formatTimeAgo } from '../utils/formatters';

/**
 * News: everything the ingest worker stored and scored -- company, sector,
 * market, macro and global -- newest first, with what each item moves.
 * A material alert on the socket re-fetches, so the page stays current.
 */

const SCOPES = [
  { id: '', label: 'All' },
  { id: 'COMPANY', label: 'Company' },
  { id: 'SECTOR', label: 'Sector' },
  { id: 'MARKET', label: 'Market' },
  { id: 'MACRO', label: 'Macro' },
  { id: 'GLOBAL', label: 'Global' },
];
const PAGE = 50;

const Impact = ({ impact }) => (
  <span
    className={cn(
      'field-label whitespace-nowrap',
      impact.direction > 0 ? 'text-[var(--gain)]' : impact.direction < 0 ? 'text-[var(--loss)]' : 'text-[var(--ink-soft)]'
    )}
  >
    {impact.type === 'market' ? 'Market' : impact.target} {impact.direction > 0 ? '↑' : impact.direction < 0 ? '↓' : '·'} {impact.impact}/10
  </span>
);

const Item = ({ item }) => (
  <li className="py-2.5">
    <a href={item.url} target="_blank" rel="noreferrer" className="block text-sm font-semibold hover:text-[var(--stamp)]">
      {item.material && <span className="field-label text-[var(--stamp)] mr-1.5">Material</span>}
      {item.title}
    </a>
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 items-baseline">
      <span className="doc-meta">{[item.scope, item.source, formatTimeAgo(item.published_at)].filter(Boolean).join(' · ')}</span>
      {(item.impacts || [])
        .slice()
        .sort((a, b) => b.impact - a.impact)
        .slice(0, 4)
        .map((impact) => <Impact key={`${impact.type}-${impact.target}`} impact={impact} />)}
      {item.status !== 'SCORED' && <span className="doc-meta normal-case">scoring…</span>}
    </div>
  </li>
);

const News = () => {
  const [scope, setScope] = useState('');
  // Names you hold or watch first; the whole wire is one tap away.
  const [mine, setMine] = useState(true);
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [more, setMore] = useState(false);

  const load = (before) => {
    const params = { limit: PAGE, ...(scope && { scope }), ...(mine && { mine: true }), ...(before && { before }) };
    return api
      .get(endpoints.newsFeed, { params })
      .then((res) => {
        setItems((current) => (before ? [...(current || []), ...res.data.items] : res.data.items));
        setMore(res.data.items.length === PAGE);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the news'));
  };

  useEffect(() => {
    setItems(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, mine]);
  useReconnect(() => load());
  useTopic('news', () => load());

  return (
    <Layout>
      <div className="space-y-4">
        <SectionTabs tabs={RESEARCH_TABS} label="Research" />
        <Sheet
          title="News"
          actions={
            <label className="flex items-center gap-2 text-sm min-h-9 cursor-pointer">
              <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
              My names
            </label>
          }
        >
          <Tabs tabs={SCOPES} active={scope} onSelect={setScope} label="News scope" className="static mb-2" />
          {error ? (
            <Empty title="Could not load the news" detail={error} />
          ) : items === null ? (
            <Ruling rows={6} />
          ) : items.length === 0 ? (
            <Empty
              title="Nothing here yet"
              detail={mine ? 'No recent news on the names you hold or watch.' : 'No stored news for this filter.'}
              action={mine && (
                <button type="button" onClick={() => setMine(false)}
                        className="min-h-11 px-3 text-sm border border-[var(--rule-strong)]">
                  Show all news
                </button>
              )}
            />
          ) : (
            <>
              <ul className="divide-y divide-[var(--rule)]">
                {items.map((item) => <Item key={item.id} item={item} />)}
              </ul>
              {more && (
                <button
                  type="button"
                  onClick={() => load(items[items.length - 1].published_at)}
                  className="mt-2 min-h-11 px-3 text-sm border border-[var(--rule-strong)]"
                >
                  Older
                </button>
              )}
            </>
          )}
        </Sheet>
      </div>
    </Layout>
  );
};

export default News;
