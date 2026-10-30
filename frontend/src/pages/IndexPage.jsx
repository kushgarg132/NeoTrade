import React, { useEffect, useState } from 'react';
import { ImpactChips, NewsLink } from '../components/common/NewsImpacts';
import { useParams, Link } from 'react-router-dom';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Hero from '../components/ui/Hero';
import DeltaChip from '../components/ui/DeltaChip';
import Stat from '../components/ui/Stat';
import Button from '../components/ui/Button';
import { AiCard, AiText } from '../components/ai/AiSummary';
import useStored from '../hooks/useStored';
import api, { endpoints } from '../utils/api';
import { stream } from '../lib/ws';
import { points } from '../components/ui/format';
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

/** On open only the stored story (`?cached=true`, no model call; 404 = none yet: status `none`). `generate`
 *  writes one: the socket streams it as it is written; HTTP is the fallback when there is no socket. */
const useIndexWhy = (ticker) => {
  const [state, setState] = useState({ ticker, status: 'loading', text: '', data: null, code: null });
  // Runs asked for on this ticker; another ticker's count reads as 0, so opening an index never runs one.
  const [run, setRun] = useState({ ticker, n: 0 });
  const tick = run.ticker === ticker ? run.n : 0;
  useEffect(() => {
    let live = true;
    const base = (s) => (s.ticker === ticker ? s : { ticker, status: 'loading', text: '', data: null, code: null });
    const set = (next) => live && setState((s) => ({ ...base(s), ...next }));
    if (!tick) {
      api.get(endpoints.marketIndexAnalysis(ticker), { params: { cached: true } })
        .then((r) => set({ status: 'ok', data: r.data }))
        .catch((e) => set(e?.response?.status === 404 ? { status: 'none' } : { status: 'error', code: e?.response?.status ?? null }));
      return () => { live = false; };
    }
    const request = stream.request('index_why', { ticker }, (m) => {
      if (m.event === 'delta') live && setState((s) => ({ ...base(s), text: base(s).text + m.data.text }));
      else if (m.event === 'report') set({ status: 'ok', data: m.data, text: '' });
      else if (m.event === 'error') set({ status: 'error', code: m.data.code ?? null, text: '' });
    });
    if (!request.ok) {
      api.get(endpoints.marketIndexAnalysis(ticker))
        .then((r) => set({ status: 'ok', data: r.data }))
        .catch((e) => set({ status: 'error', code: e?.response?.status ?? null }));
    }
    return () => { live = false; request.cancel(); };
  }, [ticker, tick]);
  const shown = state.ticker === ticker ? state : { status: 'loading', text: '', data: null, code: null };
  const generate = () => {
    setState({ ticker, status: 'loading', text: '', data: null, code: null });
    setRun((r) => ({ ticker, n: (r.ticker === ticker ? r.n : 0) + 1 }));
  };
  return { ...shown, generate };
};

const Why = ({ ticker }) => {
  const { data, status, code, text, generate } = useIndexWhy(ticker);
  return (
    <AiCard title="Why it moved" asOf={data?.session?.date}>
      {status === 'loading' && (text ? <AiText text={text} /> : <Skeleton rows={4} />)}
      {status === 'none' && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[14px] text-[var(--text-muted)]">No explanation for the last session yet.</p>
          <Button onClick={generate}>Generate explanation</Button>
        </div>
      )}
      {status === 'error' && (
        <ErrorLine message={code === 503 ? 'Explanation unavailable right now' : 'Could not load the explanation.'} onRetry={generate} />
      )}
      {status === 'ok' && (
        <>
          <AiText text={data.analysis} />
          {data.headlines?.length > 0 && (
            <ul className="mt-3 space-y-2 text-[13px] text-[var(--text-muted)]">
              {data.headlines.slice(0, 3).map((h) => (
                <li key={h.title}>
                  <NewsLink id={h.id} url={h.url} className="text-[var(--text)] hover:underline underline-offset-4">{h.title}</NewsLink>
                  <ImpactChips impacts={h.impacts} className="mt-0.5" />
                </li>
              ))}
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
      <PageHeader title={data?.name || 'Index'} back="/market" backLabel="Market" />
      {status === 'loading' && <Skeleton rows={6} />}
      {status === 'empty' && <Empty title="Not found" body="This index is not tracked." action={<Link to="/market" className="text-[var(--accent)]">Back to Market</Link>} />}
      {status === 'error' && <ErrorLine message="Could not load this index." onRetry={retry} />}
      {status === 'ok' && (
        <div className="space-y-3">
          <Hero label={data.name} value={data.value} format={points} privateValue={false}
            change={<DeltaChip value={data.change} pct={data.percent} format={points} privateValue={false} />} />
          <Card>
            <div className="grid grid-cols-2 gap-3">
              <Stat label="52-week range" value={`${num(data.low_52w)} - ${num(data.high_52w)}`} />
              <Stat label="50-day average" value={data.sma_50 == null ? 'n/a' : num(data.sma_50)} />
              <Stat label="200-day average" value={data.sma_200 == null ? 'n/a' : num(data.sma_200)} />
            </div>
            {data.points?.length > 1 && <div className="mt-3"><CloseLine points={data.points} /></div>}
          </Card>
        </div>
      )}
      {/* Under the chart, on its own read: it shows even while the price data loads or fails. */}
      {status !== 'empty' && <div className="mt-3"><Why ticker={ticker} /></div>}
    </Layout>
  );
};

export default IndexPage;
