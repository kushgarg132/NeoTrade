import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { newsPath } from '../../utils/routes';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import Badge from '../ui/Badge';
import api, { endpoints } from '../../utils/api';
import { useReconnect, useTopic } from '../../hooks/useStream';
import { formatTimeAgo } from '../../utils/formatters';
import { impactWord, materialToday } from '../../utils/market';
import { mergeFront } from '../../utils/news';

/**
 * News: everything the ingest worker stored and scored, newest first, with what each
 * item moves. "My names" (holdings and watchlist) is on first; a material alert on the
 * socket re-fetches, so the list stays current.
 */
const SCOPES = [
  { id: '', label: 'All' }, { id: 'COMPANY', label: 'Company' }, { id: 'SECTOR', label: 'Sector' },
  { id: 'MARKET', label: 'Market' }, { id: 'MACRO', label: 'Macro' }, { id: 'GLOBAL', label: 'Global' },
];
const PAGE = 50;

const Impact = ({ impact }) => {
  const arrow = impact.direction > 0 ? '↑' : impact.direction < 0 ? '↓' : '·';
  const cls = impact.direction > 0 ? 'text-[var(--gain)]' : impact.direction < 0 ? 'text-[var(--loss)]' : 'text-[var(--text-muted)]';
  return <span className={`text-[13px] tabular-nums whitespace-nowrap ${cls}`}>{impact.type === 'market' ? 'Market' : impact.target} {arrow} {impactWord(impact.impact)}</span>;
};

const BAR = { 1: 'bg-[var(--gain)]', '-1': 'bg-[var(--loss)]' };
const barClass = (item) => {
  const top = (item.impacts || []).reduce((a, b) => (b.impact > (a?.impact ?? -1) ? b : a), null);
  return BAR[Math.sign(top?.direction || 0)] || 'bg-[var(--text-muted)]';
};

const Item = ({ item }) => (
  <li className="relative py-3 pl-4 border-b border-[var(--border)] last:border-b-0">
    <span aria-hidden="true" className={`absolute left-0 top-3 bottom-3 w-[3px] rounded-full ${barClass(item)}`} />
    <Link to={newsPath(item.id)} className="block min-h-11 text-[15px] font-medium text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
      {item.material && <span className="mr-1.5 align-middle"><Badge kind="alert">Material</Badge></span>}
      {item.title}
    </Link>
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 items-baseline">
      <span className="text-[13px] text-[var(--text-muted)]">{[item.scope, item.source, formatTimeAgo(item.published_at)].filter(Boolean).join(' · ')}</span>
      {(item.impacts || []).slice().sort((a, b) => b.impact - a.impact).slice(0, 4)
        .map((impact) => <Impact key={`${impact.type}-${impact.target}`} impact={impact} />)}
      {item.status !== 'SCORED' && <span className="text-[13px] text-[var(--text-muted)]">scoring…</span>}
    </div>
  </li>
);

const Group = ({ label, items }) => items.length > 0 && (
  <section aria-label={label}>
    <h3 className="pt-2 pb-1 text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</h3>
    <ul>{items.map((item) => <Item key={item.id} item={item} />)}</ul>
  </section>
);

const News = () => {
  const [scope, setScope] = useState('');
  const [mine, setMine] = useState(true);
  const [items, setItems] = useState(null);
  const [error, setError] = useState(false);
  const [more, setMore] = useState(false);

  const [gen] = useState({ n: 0 }); // bumped on every scope change; older replies are dropped

  // before = page older items; refresh = background re-fetch of page 1 merged in front (never replaces or wipes the list).
  const load = useCallback((before, refresh) => {
    const mark = gen.n;
    const params = { limit: PAGE, ...(scope && { scope }), ...(mine && { mine: true }), ...(before && { before }) };
    return api.get(endpoints.newsFeed, { params })
      .then((res) => {
        if (mark !== gen.n) return;
        setItems((cur) => (before ? [...(cur || []), ...res.data.items] : refresh ? mergeFront(cur, res.data.items) : res.data.items));
        if (!refresh) setMore(res.data.items.length === PAGE);
        setError(false);
      })
      .catch(() => { if (mark === gen.n && !refresh) setError(true); });
  }, [scope, mine, gen]);

  useEffect(() => { load(); return () => { gen.n++; }; }, [load, gen]);
  const pickScope = (id) => { setItems(null); setScope(id); };
  const pickMine = (v) => { setItems(null); setMine(v); };
  const { pinned, rest } = materialToday(items || [], new Date());
  useReconnect(() => load(undefined, true));
  useTopic('news', () => load(undefined, true));

  return (
    <Card title="News" action={
      <label className="inline-flex items-center gap-2 min-h-11 text-[14px] text-[var(--text)] cursor-pointer">
        <input type="checkbox" checked={mine} onChange={(e) => pickMine(e.target.checked)} className="w-4 h-4 accent-[var(--accent)]" />
        My names
      </label>
    }>
      <div role="group" aria-label="News scope" className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-3 pt-1">
        {SCOPES.map((s) => (
          <button key={s.id} type="button" aria-pressed={scope === s.id} onClick={() => pickScope(s.id)}
                  className={`shrink-0 min-h-11 px-3.5 rounded-full text-[14px] font-medium border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] active:opacity-70 ${scope === s.id ? 'bg-[var(--accent)] text-[var(--accent-ink)] border-[var(--accent)]' : 'bg-[var(--surface)] text-[var(--text)] border-[var(--border)]'}`}>
            {s.label}
          </button>
        ))}
      </div>
      {error ? <ErrorLine message="Could not load the news." onRetry={() => { setItems(null); load(); }} />
        : items === null ? <Skeleton rows={6} />
        : items.length === 0 ? (
          <Empty title="Nothing here yet"
                 body={mine ? 'No recent news on the names you hold or watch.' : 'No stored news for this filter.'}
                 action={mine && <Button variant="secondary" onClick={() => pickMine(false)}>Show all news</Button>} />
        ) : (
          <>
            <Group label="Material today" items={pinned} />
            {pinned.length > 0 && rest.length > 0 && <h3 className="pt-3 pb-1 text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Earlier</h3>}
            {rest.length > 0 && <ul>{rest.map((item) => <Item key={item.id} item={item} />)}</ul>}
            {more && <Button variant="secondary" className="mt-3 w-full" onClick={() => load(items[items.length - 1].published_at)}>Older</Button>}
          </>
        )}
    </Card>
  );
};

export default News;
