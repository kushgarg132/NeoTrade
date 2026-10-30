import React, { useState } from 'react';
import Card from '../ui/Card';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import ListRow from '../ui/ListRow';
import Skeleton from '../ui/Skeleton';
import { Segmented } from '../settings/Fields';
import useStored from '../../hooks/useStored';
import { endpoints } from '../../utils/api';
import { newsPath } from '../../utils/routes';
import { formatClock } from '../../utils/formatters';
import { FILTERS, groupNews } from './newsGroups';

const SHOWN = 30;
/** This stock's scored news (last 30 days, opens the news page), headlines from your own data, plus the
 *  AI read's articles once that has run, grouped by day with a filter and a sort. Needs no AI analysis
 *  to show anything. Only scored items carry a direction and impact, so the filters other than All
 *  show those alone. */
const NewsTab = ({ symbol, mine, ai, onAnalysis }) => {
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('newest');
  const scored = useStored(endpoints.newsHistory(symbol, 30));
  const rows = [
    ...(scored.data?.items || []).slice(0, SHOWN).map((n) => ({
      key: n.id, title: n.title, to: newsPath(n.id), at: n.published_at,
      direction: n.direction, impact: n.impact, material: n.material,
    })),
    ...(mine?.news || []).map((n) => ({ key: n.id || n.url || n.headline, title: n.headline || n.title, url: n.url, at: n.published_at || n.published })),
    ...(ai?.data?.news_articles || []).map((n) => ({ key: n.url || n.title, title: n.title, url: n.url, at: n.published_at, source: n.source })),
  ].filter((r, i, all) => r.title && all.findIndex((x) => x.title === r.title) === i);
  if (!rows.length && scored.status === 'loading') return <Skeleton rows={4} />;
  if (!rows.length)
    return <Empty title="No headlines yet" body="No scored news on this stock in the last 30 days. The AI analysis also reads the latest press." action={<Button variant="secondary" onClick={onAnalysis}>Open analysis</Button>} />;
  const groups = groupNews(rows, filter, sort);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented label="Filter news" options={FILTERS} value={filter} onChange={setFilter} />
        <select aria-label="Sort news" value={sort} onChange={(e) => setSort(e.target.value)}
                className="min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 text-[14px] text-[var(--text)]">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="impact">Biggest impact</option>
        </select>
      </div>
      {!groups.length && <Empty title="Nothing matches" body="No headline here fits this filter. Scored news alone carries a direction and impact." />}
      {groups.map(([label, list]) => (
        <section key={label} aria-label={label}>
          <h3 className="px-1 pb-1.5 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</h3>
          <Card>
            {list.map((r) => {
              const score = r.impact != null && `${r.direction > 0 ? '↑' : r.direction < 0 ? '↓' : '·'} ${r.impact}/10`;
              const sub = [r.source, r.at && formatClock(r.at), score].filter(Boolean).join(' · ');
              if (r.to) return <ListRow key={r.key} to={r.to} title={r.title} sub={sub} />;
              return r.url ? (
                <a key={r.key} href={r.url} target="_blank" rel="noreferrer" className="block min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
                  <div className="text-[15px] font-medium text-[var(--text)]">{r.title}</div>
                  {sub && <div className="text-[13px] text-[var(--text-muted)]">{sub}</div>}
                </a>
              ) : (
                <ListRow key={r.key} title={r.title} sub={sub} chevron={false} />
              );
            })}
          </Card>
        </section>
      ))}
    </div>
  );
};

export default NewsTab;
