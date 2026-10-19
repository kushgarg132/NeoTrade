import React from 'react';
import Card from '../ui/Card';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import ListRow from '../ui/ListRow';
import { formatTimeAgo } from '../../utils/formatters';

/** Scored headlines from your own data, plus the AI read's articles once that has run. */
const NewsTab = ({ mine, ai, onAnalysis }) => {
  const rows = [
    ...(mine?.news || []).map((n) => ({ key: n.id || n.url || n.headline, title: n.headline || n.title, url: n.url, at: n.published_at || n.published })),
    ...(ai?.data?.news_articles || []).map((n) => ({ key: n.url || n.title, title: n.title, url: n.url, at: n.published_at, source: n.source })),
  ].filter((r, i, all) => r.title && all.findIndex((x) => x.title === r.title) === i);
  if (!rows.length)
    return <Empty title="No headlines yet" body="The AI analysis reads the latest press for this stock." action={<Button variant="secondary" onClick={onAnalysis}>Open analysis</Button>} />;
  return (
    <Card>
      {rows.map((r) => {
        const sub = [r.source, r.at && formatTimeAgo(r.at)].filter(Boolean).join(' · ');
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
