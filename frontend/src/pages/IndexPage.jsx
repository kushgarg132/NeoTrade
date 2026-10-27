import React from 'react';
import { useParams, Link } from 'react-router-dom';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Stat from '../components/ui/Stat';
import { AiCard, AiText } from '../components/ai/AiSummary';
import useStored from '../hooks/useStored';
import { endpoints } from '../utils/api';
import { pct, tone } from '../components/ui/format';
import { AXIS, GRID, SERIES, TOOLTIP_STYLE } from '../components/ui/chartTheme';

const num = (n) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });

/** A year of closes as one line. */
const CloseLine = ({ points }) => (
  <div role="img" aria-label="Closing level over the past year" className="h-40">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="date" {...AXIS} minTickGap={48} tickFormatter={(d) => new Date(d).toLocaleDateString('en-IN', { month: 'short', timeZone: 'UTC' })} />
        <YAxis {...AXIS} width={48} domain={['auto', 'auto']} tickFormatter={(v) => num(v)} />
        <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [num(v), 'Close']} />
        <Line type="monotone" dataKey="close" stroke={SERIES[0]} strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  </div>
);

const Why = ({ ticker }) => {
  const { data, status, code, retry } = useStored(endpoints.marketIndexAnalysis(ticker));
  return (
    <AiCard title="Why it moved" asOf={data?.session?.date}>
      {status === 'loading' && <Skeleton rows={4} />}
      {(status === 'error' || status === 'empty') && (
        <ErrorLine message={code === 503 ? 'Explanation unavailable right now' : 'Could not load the explanation.'} onRetry={retry} />
      )}
      {status === 'ok' && (
        <>
          <AiText text={data.analysis} />
          {data.headlines?.length > 0 && (
            <ul className="mt-3 list-disc pl-5 text-[13px] text-[var(--text-muted)]">
              {data.headlines.slice(0, 3).map((h) => <li key={h.title}>{h.title}</li>)}
            </ul>
          )}
        </>
      )}
    </AiCard>
  );
};

const IndexPage = () => {
  const { ticker } = useParams();
  const { data, status, retry } = useStored(endpoints.marketIndex(ticker));
  return (
    <Layout>
      <PageHeader title={data?.name || 'Index'} back="/market?tab=pulse" backLabel="Market" />
      {status === 'loading' && <Skeleton rows={6} />}
      {status === 'empty' && <Empty title="Not found" body="This index is not tracked." action={<Link to="/market?tab=pulse" className="text-[var(--accent)]">Back to Market</Link>} />}
      {status === 'error' && <ErrorLine message="Could not load this index." onRetry={retry} />}
      {status === 'ok' && (
        <div className="space-y-3">
          <Card>
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Level" value={num(data.value)} delta={`${data.change > 0 ? '+' : ''}${num(data.change)} (${pct(data.percent / 100, { sign: true })})`} tone={tone(data.percent)} />
              <Stat label="52-week range" value={`${num(data.low_52w)} - ${num(data.high_52w)}`} />
              <Stat label="50-day average" value={data.sma_50 == null ? 'n/a' : num(data.sma_50)} />
              <Stat label="200-day average" value={data.sma_200 == null ? 'n/a' : num(data.sma_200)} />
            </div>
            {data.points?.length > 1 && <div className="mt-3"><CloseLine points={data.points} /></div>}
          </Card>
          <Why ticker={ticker} />
        </div>
      )}
    </Layout>
  );
};

export default IndexPage;
