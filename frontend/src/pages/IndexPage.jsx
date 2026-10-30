import React, { useEffect, useState } from 'react';
import { ImpactChips, NewsLink } from '../components/common/NewsImpacts';
import { useParams, Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Hero from '../components/ui/Hero';
import DeltaChip from '../components/ui/DeltaChip';
import Button from '../components/ui/Button';
import { AiCard, AiText } from '../components/ai/AiSummary';
import useStored from '../hooks/useStored';
import api, { endpoints } from '../utils/api';
import { stream } from '../lib/ws';
import { pct, points, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import ListRow from '../components/ui/ListRow';
import TradingChart from '../components/stock/TradingChart';
import { newsPath } from '../utils/routes';
import { formatTimeAgo, marketPhase } from '../utils/formatters';
import { rangeAt } from '../utils/market';
import { sourceName } from '../utils/newsItem';

const num = (n) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 });

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

const TABS = [{ id: 'chart', label: 'Chart' }, { id: 'news', label: 'News' }, { id: 'details', label: 'Details' }];
// Indian indices read the market news; the rest the global feed.
const scopeOf = (ticker) => (/^\^(NSE|BSE|CNX)|INDIA/.test(ticker) ? 'MARKET' : 'GLOBAL');

/** The news that moves this index: the market (or global) feed, newest first, each with its analysis. */
const IndexNews = ({ ticker }) => {
  const [s, setS] = useState({ ticker: null, items: null, error: false });
  useEffect(() => {
    let live = true;
    api.get(endpoints.newsFeed, { params: { scope: scopeOf(ticker), limit: 20 } })
      .then((r) => live && setS({ ticker, items: r.data.items || [], error: false }))
      .catch(() => live && setS({ ticker, items: null, error: true }));
    return () => { live = false; };
  }, [ticker]);
  const mine = s.ticker === ticker ? s : { items: null, error: false };
  if (mine.error) return <Card><ErrorLine message="Could not load the news." onRetry={() => setS({ ticker: null, items: null, error: false })} /></Card>;
  if (!mine.items) return <Card><Skeleton rows={5} /></Card>;
  if (!mine.items.length) return <Card><Empty title="No market news yet" body="Scored market stories appear here as the news desk reads them." action={<Link to="/market?tab=news" className="text-[var(--accent)]">Open News</Link>} /></Card>;
  return (
    <Card>
      {mine.items.map((n) => (
        <ListRow privateValue={false} key={n.id} title={n.title} to={newsPath(n.id)}
          sub={[sourceName(n.source), formatTimeAgo(n.published_at)].filter(Boolean).join(' · ')}
          extra={<ImpactChips impacts={n.impacts} material={n.material} />} />
      ))}
    </Card>
  );
};

/** A public figure (an index level is nobody's money): not masked by hide-amounts, unlike ui/Stat. */
const Stat = ({ label, value, delta }) => (
  <div className="min-w-0">
    <div className="text-[13px] text-[var(--text-muted)]">{label}</div>
    <div className="text-[17px] font-semibold tabular-nums text-[var(--text)] truncate">{value}</div>
    {delta != null && <div className="text-[13px] tabular-nums">{delta}</div>}
  </div>
);

const ret = (pts, n) => (pts?.length > n ? pts[pts.length - 1].close / pts[pts.length - 1 - n].close - 1 : null);

/** The figures a reader checks: the averages and where the level sits against them, and the returns. */
const Details = ({ data }) => {
  const vs = (avg) => (avg ? data.value / avg - 1 : null);
  const line = (v) => (v == null ? null : <span className={toneText(tone(v))}>{pct(v, { sign: true, dp: 1 })}</span>);
  return (
    <Card>
      <div className="grid grid-cols-2 gap-x-3 gap-y-4 sm:grid-cols-3">
        <Stat label="52-week high" value={num(data.high_52w)} delta={line(data.high_52w ? data.value / data.high_52w - 1 : null)} />
        <Stat label="52-week low" value={num(data.low_52w)} delta={line(data.low_52w ? data.value / data.low_52w - 1 : null)} />
        <Stat label="50-day average" value={data.sma_50 == null ? 'n/a' : num(data.sma_50)} delta={line(vs(data.sma_50))} />
        <Stat label="200-day average" value={data.sma_200 == null ? 'n/a' : num(data.sma_200)} delta={line(vs(data.sma_200))} />
        <Stat label="1 year" value={line(ret(data.points, 252)) || 'n/a'} />
        <Stat label="5 years" value={line(ret(data.points, 1255)) || 'n/a'} />
      </div>
      <p className="mt-3 text-[12px] text-[var(--text-muted)]">Figures under each: where today's level sits against it.</p>
    </Card>
  );
};

/** /market/index/:ticker, laid out as a stock page: the level and its day on top with the 52-week range, the AI's
 *  read of the last session, then Chart (1D intraday to 5Y), News and Details. Nothing to buy: an index. */
const IndexPage = () => {
  const { ticker } = useParams();
  const { data, status, retry } = useStored(endpoints.marketIndex(ticker));
  const [tab, setTab] = useTabParam(TABS.map((t) => t.id), 'chart');
  const at = data ? rangeAt(data.value, data.low_52w, data.high_52w) : null;
  return (
    <Layout>
      <PageHeader title={data?.name || 'Index'} back="/market" backLabel="Market" />
      {status === 'loading' && <Card className="mb-3"><Skeleton rows={2} /></Card>}
      {status === 'empty' && <Empty title="Not found" body="This index is not tracked." action={<Link to="/market" className="text-[var(--accent)]">Back to Market</Link>} />}
      {status === 'error' && <Card className="mb-3"><ErrorLine message="Could not load this index." onRetry={retry} /></Card>}
      {status === 'ok' && (
        <div className="mb-3">
          <Hero label={data.name} value={data.value} format={points} privateValue={false}
            change={<DeltaChip value={data.change} pct={data.percent} format={points} privateValue={false} suffix={marketPhase() === 'open' ? 'today' : 'last session'} />}>
            {at != null && (
              <div className="mt-4 flex items-center gap-2 text-[12px] tabular-nums text-[var(--text-muted)]" role="img"
                aria-label={`52-week range ${num(data.low_52w)} to ${num(data.high_52w)}, now ${Math.round(at * 100)}% of the way up`}>
                <span className="shrink-0">52w {num(data.low_52w)}</span>
                <span className="relative h-1 flex-1 rounded-full bg-[var(--surface-2)]">
                  <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--surface)] bg-[var(--text)]" style={{ left: `${at * 100}%` }} />
                </span>
                <span className="shrink-0">{num(data.high_52w)}</span>
              </div>
            )}
          </Hero>
        </div>
      )}
      {status !== 'empty' && <div className="mb-3"><Why ticker={ticker} /></div>}
      {status === 'ok' && (
        <>
          <Tabs tabs={TABS} value={tab} onChange={setTab} label="Index sections" />
          <div className="mt-3">
            {tab === 'chart' && (data.points?.length > 1
              ? <Card><TradingChart closes={data.points} symbol={ticker} currency="pts" intradayUrl={endpoints.marketIndexIntraday(ticker)} newsUrl={null} /></Card>
              : <Empty title="No price data" body={`Could not load the history for ${data.name}.`} action={<Button variant="secondary" onClick={retry}>Retry</Button>} />)}
            {tab === 'news' && <IndexNews ticker={ticker} />}
            {tab === 'details' && <Details data={data} />}
          </div>
        </>
      )}
    </Layout>
  );
};

export default IndexPage;
