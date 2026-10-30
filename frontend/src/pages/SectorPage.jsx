import React from 'react';
import { useParams, Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import ListRow from '../components/ui/ListRow';
import Stat from '../components/ui/Stat';
import useStored from '../hooks/useStored';
import { endpoints } from '../utils/api';
import { pct, tone } from '../components/ui/format';
import { stockPath } from '../utils/stocks';
import { newsPath } from '../utils/routes';
import { ImpactChips } from '../components/common/NewsImpacts';
import { formatTimeAgo } from '../utils/formatters';

const SectorPage = () => {
  const { name } = useParams();
  const { data, status, retry } = useStored(endpoints.marketSector(name));
  const members = data ? [...data.members].sort((a, b) => b.change_pct - a.change_pct) : [];
  return (
    <Layout>
      <PageHeader title={name} back="/market" backLabel="Market" />
      {status === 'loading' && <Skeleton rows={6} />}
      {status === 'empty' && <Empty title="Unknown sector" body="No Nifty 200 stock is filed under this sector." action={<Link to="/market" className="text-[var(--accent)]">Back to Market</Link>} />}
      {status === 'error' && <ErrorLine message="Could not load this sector." onRetry={retry} />}
      {status === 'ok' && (
        <div className="space-y-3">
          <Card>
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Today" value={pct(data.change_pct / 100, { sign: true })} tone={tone(data.change_pct)} />
              <Stat label="Up" value={`${data.up} of ${data.n}`} />
              <Stat label="News mood" value={data.sentiment == null ? 'n/a' : `${data.sentiment > 0 ? '+' : ''}${data.sentiment.toFixed(2)}`} tone={tone(data.sentiment)} />
            </div>
          </Card>
          <Card title="Stocks">
            {members.length === 0 ? <Empty title="No quotes yet" body="Members show once the market feed has prices." /> : members.map((m) => (
              <ListRow privateValue={false} key={m.symbol} dense title={m.symbol} sub={m.name} to={stockPath(m.symbol)}
                       right={pct(m.change_pct / 100, { sign: true })} rightTone={tone(m.change_pct)} />
            ))}
          </Card>
          <Card title="News moving this sector">
            {data.news.length === 0 ? <Empty title="No sector news yet" body="Stories that name this sector appear here once scored." /> : data.news.map((n) => (
              <ListRow privateValue={false} key={n.id} title={n.title} sub={[n.source, formatTimeAgo(n.published_at)].filter(Boolean).join(' · ')} to={newsPath(n.id)}
                       extra={<ImpactChips impacts={n.impacts} material={n.material} />} />
            ))}
          </Card>
        </div>
      )}
    </Layout>
  );
};

export default SectorPage;
