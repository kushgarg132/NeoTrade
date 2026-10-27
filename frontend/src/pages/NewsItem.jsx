import React from 'react';
import { useParams, Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import ListRow from '../components/ui/ListRow';
import Badge from '../components/ui/Badge';
import useStored from '../hooks/useStored';
import { endpoints } from '../utils/api';
import { pct, tone } from '../components/ui/format';
import { stockPath } from '../utils/stocks';
import { sectorPath } from '../utils/routes';
import { outcomeRows } from '../utils/newsItem';
import { formatDateTime } from '../utils/formatters';
import { toneText } from '../components/ui/tone';

/** Stock and sector targets link to their pages; the market itself has none. */
const targetLink = (i) => (i.type === 'symbol' ? stockPath(i.target) : i.type === 'sector' ? sectorPath(i.target) : null);

const Impact = ({ i }) => {
  const arrow = i.direction > 0 ? '↑' : i.direction < 0 ? '↓' : '·';
  const signed = i.direction * i.impact;
  const to = targetLink(i);
  const label = i.type === 'market' ? 'Market' : i.target;
  return (
    <li className="flex items-baseline justify-between gap-3 py-2 border-b border-[var(--border)] last:border-b-0 text-[15px]">
      {to ? <Link to={to} className="text-[var(--accent)]">{label}</Link> : <span className="text-[var(--text)]">{label}</span>}
      <span className={`tabular-nums ${toneText(tone(i.direction))}`}>{arrow} {signed > 0 ? '+' : ''}{signed}/10</span>
    </li>
  );
};

const NewsItem = () => {
  const { id } = useParams();
  const { data, status, retry } = useStored(endpoints.newsItem(id));
  const rows = data ? outcomeRows(data.outcomes) : [];
  return (
    <Layout>
      <PageHeader title="News" back="/market?tab=news" backLabel="News" />
      {status === 'loading' && <Skeleton rows={6} />}
      {status === 'empty' && <Empty title="Not found" body="This story is no longer stored." action={<Link to="/market?tab=news" className="text-[var(--accent)]">Back to News</Link>} />}
      {status === 'error' && <ErrorLine message="Could not load this story." onRetry={retry} />}
      {status === 'ok' && (
        <div className="space-y-3">
          <Card>
            <h2 className="text-[17px] font-semibold text-[var(--text)]">
              {data.material && <span className="mr-1.5 align-middle"><Badge kind="alert">Material</Badge></span>}
              {data.title}
            </h2>
            <p className="mt-1 text-[13px] text-[var(--text-muted)]">{[data.source, formatDateTime(data.published_at)].filter(Boolean).join(' · ')}</p>
            {data.url && <a href={data.url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center min-h-11 text-[14px] font-medium text-[var(--accent)]">Read article ↗</a>}
          </Card>
          <Card title="What it moves">
            {data.impacts?.length ? <ul>{data.impacts.map((i) => <Impact key={`${i.type}-${i.target}`} i={i} />)}</ul>
              : <Empty title="Not scored yet" body="Impacts appear once the news desk has scored this story." />}
          </Card>
          <Card title="What the market did">
            {rows.length === 0 ? <Empty title="Not scored yet" body="Price outcomes fill in after 1 hour, 1 day and 5 days." />
              : rows.map((r) => (
                <ListRow privateValue={false} key={`${r.target}-${r.horizon}`} dense title={`${r.target} · ${r.horizon}`}
                         sub={`${pct(r.vsBench, { sign: true })} vs Nifty`} right={pct(r.move, { sign: true })} rightTone={tone(r.move)} />
              ))}
          </Card>
        </div>
      )}
    </Layout>
  );
};

export default NewsItem;
