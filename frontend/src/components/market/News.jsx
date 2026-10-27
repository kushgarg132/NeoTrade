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
  return <span className={`text-[13px] tabular-nums whitespace-nowrap ${cls}`}>{impact.type === 'market' ? 'Market' : impact.target} {arrow} {impact.impact}/10</span>;
};

const Item = ({ item }) => (
  <li className="py-3 border-b border-[var(--border)] last:border-b-0">
    <Link to={newsPath(item.id)} className="block text-[15px] font-medium text-[var(--text)]">
      {item.material && <span className="mr-1.5 align-middle"><Badge kind="alert">Material</Badge></span>}
      {item.title}
    </Link>
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 items-baseline">
      <span className="text-[13px] text-[var(--text-muted)]">{[item.scope, item.source, formatTimeAgo(item.published_at)].filter(Boolean).join(' · ')}</span>
      {(item.impacts || []).slice().sort((a, b) => b.impact - a.impact).slice(0, 4)
        .map((impact) => <Impact key={`${impact.type}-${impact.target}`} impact={impact} />)}
      {item.status !== 'SCORED' && <span className="text-[13px] text-[var(--text-muted)]">scoring…</span>}
    </div>
  </li>
);

const News = () => {
  const [scope, setScope] = useState('');
  const [mine, setMine] = useState(true);
  const [items, setItems] = useState(null);
  const [error, setError] = useState(false);
  const [more, setMore] = useState(false);

  const load = useCallback((before) => {
    const params = { limit: PAGE, ...(scope && { scope }), ...(mine && { mine: true }), ...(before && { before }) };
    return api.get(endpoints.newsFeed, { params })
      .then((res) => {
        setItems((cur) => (before ? [...(cur || []), ...res.data.items] : res.data.items));
        setMore(res.data.items.length === PAGE);
        setError(false);
      })
      .catch(() => setError(true));
  }, [scope, mine]);

  useEffect(() => { load(); }, [load]);
  const pickScope = (id) => { setItems(null); setScope(id); };
  const pickMine = (v) => { setItems(null); setMine(v); };
  useReconnect(() => load());
  useTopic('news', () => load());

  return (
    <Card title="News" action={
      <label className="inline-flex items-center gap-2 min-h-11 text-[14px] text-[var(--text)] cursor-pointer">
        <input type="checkbox" checked={mine} onChange={(e) => pickMine(e.target.checked)} className="w-4 h-4 accent-[var(--accent)]" />
        My names
      </label>
    }>
      <div role="group" aria-label="News scope" className="flex gap-2 overflow-x-auto pb-3">
        {SCOPES.map((s) => (
          <button key={s.id} type="button" aria-pressed={scope === s.id} onClick={() => pickScope(s.id)}
                  className={`shrink-0 min-h-11 px-3.5 rounded-full text-[14px] font-medium border ${scope === s.id ? 'bg-[var(--accent)] text-[var(--surface)] border-[var(--accent)]' : 'bg-[var(--surface)] text-[var(--text)] border-[var(--border)]'}`}>
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
            <ul>{items.map((item) => <Item key={item.id} item={item} />)}</ul>
            {more && <Button variant="secondary" className="mt-3 w-full" onClick={() => load(items[items.length - 1].published_at)}>Older</Button>}
          </>
        )}
    </Card>
  );
};

export default News;
