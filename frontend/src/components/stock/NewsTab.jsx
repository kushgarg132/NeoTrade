import React from 'react';
import Card from '../ui/Card';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import ListRow from '../ui/ListRow';
import Skeleton from '../ui/Skeleton';
import useStored from '../../hooks/useStored';
import { endpoints } from '../../utils/api';
import { newsPath } from '../../utils/routes';
import { formatTimeAgo } from '../../utils/formatters';

const SHOWN = 30;

/** This stock's scored news (last 30 days, opens the news page), headlines from your own data, plus the
 *  AI read's articles once that has run. Needs no AI analysis to show anything. */
const NewsTab = ({ symbol, mine, ai, onAnalysis }) => {
  const scored = useStored(endpoints.newsHistory(symbol, 30));
  const rows = [
    ...(scored.data?.items || []).slice(0, SHOWN).map((n) => ({ key: n.id, title: n.title, to: newsPath(n.id), at: n.published_at })),
    ...(mine?.news || []).map((n) => ({ key: n.id || n.url || n.headline, title: n.headline || n.title, url: n.url, at: n.published_at || n.published })),
    ...(ai?.data?.news_articles || []).map((n) => ({ key: n.url || n.title, title: n.title, url: n.url, at: n.published_at, source: n.source })),
  ].filter((r, i, all) => r.title && all.findIndex((x) => x.title === r.title) === i);
  if (!rows.length && scored.status === 'loading') return <Skeleton rows={4} />;
  if (!rows.length)
    return <Empty title="No headlines yet" body="No scored news on this stock in the last 30 days. The AI analysis also reads the latest press." action={<Button variant="secondary" onClick={onAnalysis}>Open analysis</Button>} />;
  return (
    <Card>
      {rows.map((r) => {
        const sub = [r.source, r.at && formatTimeAgo(r.at)].filter(Boolean).join(' · ');
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
  );
};

export default NewsTab;
