import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Star } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Hero from '../components/ui/Hero';
import DeltaChip from '../components/ui/DeltaChip';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Empty from '../components/ui/Empty';
import AsOf from '../components/ui/AsOf';
import { inr, pct, points, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import OrderTicket from '../components/trading/OrderTicket';
import TradingChart from '../components/stock/TradingChart';
import NewsTab from '../components/stock/NewsTab';
import DetailsTab from '../components/stock/DetailsTab';
import AiRead from '../components/stock/AiRead';
import EventsTab from '../components/stock/EventsTab';
import useStockAnalysis from '../components/stock/useStockAnalysis';
import Fundamentals from '../components/analysis/Fundamentals';
import { verdictKind, verdictLabel } from '../components/stock/common';
import { StockIcon } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { bareSymbol, formatQuantity, marketPhase } from '../utils/formatters';
import { stockTab } from '../utils/stocks';
import { positionSummary } from '../utils/stock';
import { px } from '../components/ideas/levels';

const TABS = [
  { id: 'chart', label: 'Chart' },
  { id: 'news', label: 'News' },
  { id: 'details', label: 'Details' },
  { id: 'events', label: 'Events' },
];

const cause = (e) => (e && e !== 'Could not load' ? `: ${e}` : '');

const Stat = ({ label, value, valueClass = '' }) => (
  <div className="min-w-0">
    <div className="text-[13px] text-[var(--text-muted)]">{label}</div>
    <div className={`private text-[15px] font-semibold tabular-nums truncate ${valueClass}`}>{value}</div>
  </div>
);

/** /stock/:symbol: price and verdict on top, your position if you hold it, then Chart / News / Details / Events. */
const Stock = () => {
  const symbol = bareSymbol(useParams().symbol)?.toUpperCase();
  const [tab, setTab] = useTabParam(TABS.map((t) => t.id), 'chart', 'tab', (t) => (t === 'analysis' ? stockTab(t) : t));
  const [params] = useSearchParams();
  const { quick, ai, aiRead, retryAi, reloadQuick } = useStockAnalysis(symbol);
  // Old ?tab=analysis links land on Details.
  const legacy = params.get('tab') === 'analysis';
  useEffect(() => { if (legacy) setTab(stockTab('analysis')); }, [legacy, setTab]);

  // Your side of the stock: 404 means you have never held it, which is not an error.
  const [mineRaw, setMine] = useState({ data: null, status: 'loading', symbol }); // loading | ok | missing | error
  const mine = mineRaw.symbol === symbol ? mineRaw : { data: null, status: 'loading' }; // another stock's answer is not ours
  const [portfolio, setPortfolio] = useState(null);
  const [ticket, setTicket] = useState(null);
  const loadMine = useCallback(() => {
    api
      .get(endpoints.mine.stock(symbol))
      .then((res) => setMine({ data: res.data, status: 'ok', symbol }))
      .catch((err) => setMine({ data: null, status: err?.response?.status === 404 ? 'missing' : 'error', symbol }));
  }, [symbol]);
  useEffect(loadMine, [loadMine]);

  // Watch / Watching: GET /watchlist once, then add or remove (the Watchlist page had no way to add).
  const [watchRaw, setWatch] = useState(null); // { symbol, on } | null while unknown
  const watching = watchRaw?.symbol === symbol ? watchRaw.on : null;
  useEffect(() => {
    if (!symbol) return;
    api.get(endpoints.watchlist.list)
      .then((r) => setWatch({ symbol, on: (r.data.symbols || []).some((s) => bareSymbol(s).toUpperCase() === symbol) }))
      .catch(() => {});
  }, [symbol]);
  const toggleWatch = () => {
    const on = !watching;
    setWatch({ symbol, on });
    (on ? api.post(endpoints.watchlist.add(symbol)) : api.delete(endpoints.watchlist.remove(symbol)))
      .catch(() => setWatch({ symbol, on: !on }));
  };

  // The price itself, every 60 s in session: GET /market/quotes reads the ingest quote cache.
  // The snapshot's price was a one-shot that sat still for as long as the page stayed open.
  const [liveRaw, setLive] = useState(null);
  const live = liveRaw?.symbol === symbol ? liveRaw : null;
  useEffect(() => {
    if (!symbol) return undefined;
    let current = true;
    const poll = () => api.get(endpoints.marketQuotes([symbol]))
      .then((r) => current && r.data[0] && setLive(r.data[0]))
      .catch(() => {}); // the snapshot price stands in, and AsOf turns stale
    poll();
    const timer = setInterval(() => !document.hidden && marketPhase() !== 'closed' && poll(), 60_000);
    return () => { current = false; clearInterval(timer); };
  }, [symbol]);
  useEffect(() => {
    api.get(endpoints.mine.overview).then((res) => setPortfolio(res.data?.headline?.value ?? null)).catch(() => setPortfolio(null));
  }, []);

  const m = mine.data;
  const company = quick.data?.company_info;
  const currency = company?.currency || 'INR';
  const closes = useMemo(() => {
    const fromQuick = (quick.data?.price_data || []).map((c) => ({ date: String(c.timestamp).slice(0, 10), close: Number(c.close) }));
    return (m?.closes?.length || 0) > fromQuick.length ? m.closes : fromQuick; // the longer history wins (5Y)
  }, [quick.data, m]);

  const price = live?.price ?? company?.current_price ?? closes.at(-1)?.close;
  const prev = live?.change_pct != null ? live.price / (1 + live.change_pct / 100) : company?.previous_close;
  const dayPct = live?.change_pct != null ? live.change_pct / 100
    : company?.day_change_percent != null ? company.day_change_percent / 100 : prev ? price / prev - 1 : null;
  const dayAbs = prev != null && price != null ? price - prev : null;
  const pos = positionSummary(m?.position, portfolio);
  const stop = m?.thesis?.stop;
  const risk = {
    stop: stop ?? null,
    target: m?.thesis?.target ?? null,
    stopDist: stop != null && price ? (price - stop) / price : null,
    stopPnl: stop != null && pos ? (stop - pos.avg) * pos.qty : null,
    stopFromNow: stop != null && pos && price != null ? (stop - price) * pos.qty : null,
  };
  const verdict = m?.verdict?.current;
  const sold = m?.position?.sold;

  const panel = {
    chart: (
      <div className="space-y-3">
        {closes.length >= 2 || !quick.loading ? (
          <Card>
            <TradingChart closes={closes} trades={m?.trades} thesis={m?.thesis} symbol={symbol} currency={currency} />
          </Card>
        ) : <Card><Skeleton rows={5} /></Card>}
        {company && <Fundamentals company={company} currency={currency} />}
      </div>
    ),
    news: <NewsTab symbol={symbol} mine={m} ai={ai} onAnalysis={() => document.getElementById('ai-read')?.scrollIntoView({ behavior: 'smooth' })} />,
    details: <DetailsTab mine={m} quick={quick} reloadQuick={reloadQuick} />,
    events: <EventsTab mine={m} ai={ai} />,
  }[tab];

  return (
    <Layout>
      <PageHeader title={(
        <span className="flex items-center gap-2.5 min-w-0">
          <StockIcon symbol={symbol} className="size-8 rounded-[8px] p-0.5" />
          <span className="truncate">{symbol}</span>
        </span>
      )} back right={verdict && !sold ? <Badge kind={verdictKind(verdict)}>{verdictLabel(verdict)}</Badge> : null} />

      {quick.loading && price == null ? (
        <Card className="mb-3"><Skeleton rows={2} /></Card>
      ) : quick.error && price == null ? (
        <Card className="mb-3">
          <ErrorLine message={`Could not load the price for ${symbol}${cause(quick.error)}. Check your connection and retry.`} onRetry={reloadQuick} />
        </Card>
      ) : (
        <div className="mb-3">
          <Hero
            label={company?.name || symbol}
            value={price}
            format={currency === 'INR' ? inr : points}
            privateValue={false}
            change={dayPct != null && (
              <DeltaChip
                value={currency === 'INR' ? dayAbs : null}
                pct={dayPct * 100}
                suffix={marketPhase() === 'open' ? 'today' : 'last session'}
                privateValue={false}
              />
            )}
            action={watching !== null && (
              <button type="button" onClick={toggleWatch} aria-pressed={watching}
                      className={`shrink-0 -my-3 -mr-2 min-h-11 px-2 inline-flex items-center gap-1.5 rounded-[10px] text-[13px] font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${watching ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`}>
                <Star className="w-4 h-4" fill={watching ? 'currentColor' : 'none'} aria-hidden="true" />
                {watching ? 'Watching' : 'Watch'}
              </button>
            )}
          >
            <AsOf at={live?.at} />
          </Hero>
        </div>
      )}
      {(pos || sold || mine.status === 'error') && (
        <Card className="mb-3">
        {pos && (
          <div>
            <p className="text-[13px] text-[var(--text-muted)] mb-2">Your position · your broker account</p>
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Quantity · avg" value={`${formatQuantity(pos.qty)} · ${px(pos.avg)}`} />
              <Stat
                label="P&L"
                value={`${inr(pos.pnl, { sign: true })}${pos.pnlPct != null ? ` (${pct(pos.pnlPct, { sign: true, dp: 1 })})` : ''}`}
                valueClass={toneText(tone(pos.pnl))}
              />
              {pos.value != null && <Stat label="Value now" value={inr(pos.value)} />}
              {pos.weight != null && <Stat label="Of your portfolio" value={pct(pos.weight, { dp: 1 })} />}
            </div>
            {risk.stop != null && (
            <div className="mt-2 text-[14px] text-[var(--text)]" data-testid="stop-line">
                <p>
                  Stop <span className="private">{px(risk.stop)}</span>
                  {risk.stopDist != null && (risk.stopDist > 0 ? ` · ${pct(risk.stopDist, { dp: 1 })} below price` : ' · price is at or below your stop')}
                  {' · if hit: '}
                  {risk.stopFromNow != null && <span className="private">{inr(risk.stopFromNow, { sign: true })} from now </span>}
                  <span className="private">({inr(risk.stopPnl, { sign: true })} vs what you paid)</span>
                  {risk.target != null && <> · target <span className="private">{px(risk.target)}</span></>}
                </p>
            </div>
            )}
          </div>
        )}
        {sold && <p className="text-[14px] text-[var(--text-muted)]">You no longer hold this. Past trades are on the chart.</p>}
        {mine.status === 'error' && <ErrorLine message="Could not load your position from your broker account. Prices and charts still work." onRetry={loadMine} />}
        </Card>
      )}

      <AiRead aiRead={aiRead} retryAi={retryAi} />

      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Stock sections" />
      <div className="mt-3">
        {tab === 'chart' && quick.error && !closes.length ? <Empty title="No price data" body={`Could not load the price history for ${symbol}${cause(quick.error)}.`} action={<Button variant="secondary" onClick={reloadQuick}>Retry</Button>} /> : panel}
      </div>

      <div className="h-28 lg:h-20" aria-hidden="true" />
      <div className="fixed z-30 inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] lg:bottom-0 lg:left-56 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2">
        <div className="mx-auto max-w-5xl flex gap-3">
          {pos && <Button variant="secondary" className="flex-1" onClick={() => setTicket({ symbol, side: 'SELL', lastPrice: price })}>Sell</Button>}
          <Button className="flex-1" disabled={price == null} onClick={() => setTicket({ symbol, side: 'BUY', lastPrice: price })}>{pos ? 'Buy more' : 'Buy'}</Button>
        </div>
        {price == null && <p className="mx-auto max-w-5xl mt-1 text-[13px] text-[var(--text-muted)]">Buy is off until a price loads for {symbol}.</p>}
      </div>
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={loadMine} />}
    </Layout>
  );
};

export default Stock;
