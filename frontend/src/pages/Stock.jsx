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
import { inrPaise, points } from '../components/ui/format';
import OrderTicket from '../components/trading/OrderTicket';
import TradingChart from '../components/stock/TradingChart';
import NewsTab from '../components/stock/NewsTab';
import DetailsTab from '../components/stock/DetailsTab';
import AiRead from '../components/stock/AiRead';
import EventsTab from '../components/stock/EventsTab';
import StockIndices from '../components/stock/StockIndices';
import Position from '../components/stock/Position';
import VerdictSummary from '../components/stock/VerdictSummary';
import MarketFacts from '../components/stock/MarketFacts';
import useStockAnalysis from '../components/stock/useStockAnalysis';
import Fundamentals from '../components/analysis/Fundamentals';
import { verdictKind, verdictLabel } from '../components/stock/common';
import { StockIcon } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { bareSymbol, marketPhase } from '../utils/formatters';
import useLivePoll from '../hooks/useLivePoll';
import { stockTab } from '../utils/stocks';
import { positionSummary, toBars } from '../utils/stock';
import { px } from '../components/ideas/levels';
import SignInCard from '../components/SignInCard';
import { useAuth } from '../context/AuthContext';

const TABS = [
  { id: 'chart', label: 'Chart' },
  { id: 'news', label: 'News' },
  { id: 'details', label: 'Details' },
  { id: 'events', label: 'Events' },
];

// Signed out: what a tap on a personal action shows in place of doing it.
const WATCH_OR_TRADE = { title: 'Sign in to watch or trade', body: 'Sign in to keep a watchlist and place orders through your broker.' };
const FRESH_READ = { title: 'Sign in for a fresh AI read', body: 'The stored read is free to everyone; a new one runs for signed-in accounts.' };

const cause = (e) => (e && e !== 'Could not load' ? `: ${e}` : '');

/** /stock/:symbol: price on top; when you hold it, your position (lots, plan) and the verdict's answer; the AI read and
 *  how the stock has done; then Chart / News / Details / Events. */
const Stock = () => {
  const symbol = bareSymbol(useParams().symbol)?.toUpperCase();
  const [tab, setTab] = useTabParam(TABS.map((t) => t.id), 'chart', 'tab', (t) => (t === 'analysis' ? stockTab(t) : t));
  const [params] = useSearchParams();
  const { user } = useAuth();
  const { quick, ai, aiRead, retryAi, reloadQuick } = useStockAnalysis(symbol);
  const [ask, setAsk] = useState(null); // guest: the sign-in copy for the action just tapped, on this symbol
  const askSignIn = (copy) => {
    setAsk({ symbol, ...copy });
    requestAnimationFrame(() => document.getElementById('sign-in')?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  };
  // Old ?tab=analysis links land on Details.
  const legacy = params.get('tab') === 'analysis';
  useEffect(() => { if (legacy) setTab(stockTab('analysis')); }, [legacy, setTab]);

  // Your side of the stock: 404 means you have never held it, which is not an error.
  const [mineRaw, setMine] = useState({ data: null, status: 'loading', symbol }); // loading | ok | missing | error
  // Signed out there is no position to load: read as never held.
  const mine = !user ? { data: null, status: 'missing' } : mineRaw.symbol === symbol ? mineRaw : { data: null, status: 'loading' }; // another stock's answer is not ours
  const [portfolio, setPortfolio] = useState(null);
  const [ticket, setTicket] = useState(null);
  const loadMine = useCallback(() => {
    if (!user) return;
    api
      .get(endpoints.mine.stock(symbol))
      .then((res) => setMine({ data: res.data, status: 'ok', symbol }))
      .catch((err) => setMine({ data: null, status: err?.response?.status === 404 ? 'missing' : 'error', symbol }));
  }, [symbol, user]);
  useEffect(loadMine, [loadMine]);

  // Watch / Watching: GET /watchlist once, then add or remove (the Watchlist page had no way to add).
  const [watchRaw, setWatch] = useState(null); // { symbol, on } | null while unknown
  const watching = !user ? false : watchRaw?.symbol === symbol ? watchRaw.on : null;
  useEffect(() => {
    if (!symbol || !user) return;
    api.get(endpoints.watchlist.list)
      .then((r) => setWatch({ symbol, on: (r.data.symbols || []).some((s) => bareSymbol(s).toUpperCase() === symbol) }))
      .catch(() => {});
  }, [symbol, user]);
  const toggleWatch = () => {
    if (!user) { askSignIn(WATCH_OR_TRADE); return; }
    const on = !watching;
    setWatch({ symbol, on });
    (on ? api.post(endpoints.watchlist.add(symbol)) : api.delete(endpoints.watchlist.remove(symbol)))
      .catch(() => setWatch({ symbol, on: !on }));
  };

  // The price itself, every 60 s in session: GET /market/quotes reads the ingest quote cache.
  // The snapshot's price was a one-shot that sat still for as long as the page stayed open.
  const [liveRaw, setLive] = useState(null);
  const live = liveRaw?.symbol === symbol ? liveRaw : null;
  const pollQuote = useCallback(() => (symbol
    ? api.get(endpoints.marketQuotes([symbol])).then((r) => r.data[0] && setLive(r.data[0])).catch(() => {}) // the snapshot price stands in, and AsOf turns stale
    : undefined), [symbol]);
  useEffect(() => { pollQuote(); }, [pollQuote]);
  useLivePoll(pollQuote, 60_000);
  useEffect(() => {
    if (!user) return;
    api.get(endpoints.mine.overview).then((res) => setPortfolio(res.data?.headline?.value ?? null)).catch(() => setPortfolio(null));
  }, [user]);

  const m = mine.data;
  const company = quick.data?.company_info;
  const currency = company?.currency || 'INR';
  // Daily OHLCV for the chart: quick-analyze candles or your mine.bars, the longer history wins.
  const closes = useMemo(() => {
    const fromQuick = quick.data?.price_data || [];
    const fromMine = m?.bars || [];
    return toBars(fromMine, { daily: true }).bars.length > toBars(fromQuick, { daily: true }).bars.length ? fromMine : fromQuick;
  }, [quick.data, m]);

  const price = live?.price ?? company?.current_price ?? closes.at(-1)?.close;
  const prev = live?.change_pct != null ? live.price / (1 + live.change_pct / 100) : company?.previous_close;
  const dayPct = live?.change_pct != null ? live.change_pct / 100
    : company?.day_change_percent != null ? company.day_change_percent / 100 : prev ? price / prev - 1 : null;
  const dayAbs = prev != null && price != null ? price - prev : null;
  const pos = positionSummary(m?.position, portfolio);
  const verdict = m?.verdict?.current;
  const sold = m?.position?.sold;
  // A holding opens on a daily range wide enough to show your first buy (trades and plan lines only draw on daily
  // ranges); anything else opens on today.
  const heldDays = m?.position?.held_since ? (Date.now() - new Date(m.position.held_since).getTime()) / 86_400_000 : 0;
  const chartRange = !(pos || sold) ? '1D' : heldDays > 180 ? '1Y' : '6M';

  const panel = {
    chart: (
      <div className="space-y-3">
        {closes.length >= 2 || !quick.loading ? (
          <Card>
            <TradingChart key={chartRange} initialRange={chartRange} closes={closes} trades={m?.trades} thesis={m?.thesis} symbol={symbol} currency={currency} live={price} />
          </Card>
        ) : <Card><Skeleton rows={5} /></Card>}
        {company && <Fundamentals company={company} currency={currency} />}
      </div>
    ),
    news: <NewsTab symbol={symbol} mine={m} ai={ai} onAnalysis={() => document.getElementById('ai-read')?.scrollIntoView({ behavior: 'smooth' })} />,
    details: <DetailsTab mine={m} quick={quick} reloadQuick={reloadQuick} />,
    events: <EventsTab symbol={symbol} mine={m} ai={ai} />,
  }[tab];

  return (
    <Layout>
      <PageHeader title={(
        <span className="flex items-center gap-2.5 min-w-0">
          <StockIcon symbol={symbol} className="size-8 rounded-[8px] p-0.5" />
          <span className="truncate">{symbol}</span>
        </span>
      )} back right={verdict && !sold ? (
        <button type="button" onClick={() => setTab('details')} aria-label={`Verdict ${verdictLabel(verdict)}: see why`} className="tap inline-flex min-h-11 items-center rounded-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
          <Badge kind={verdictKind(verdict)}>{verdictLabel(verdict)}</Badge>
        </button>
      ) : null} />

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
            format={currency === 'INR' ? px : points} // paise, as the chart readout and your average price print it
            privateValue={false}
            change={dayPct != null && (
              <DeltaChip
                value={currency === 'INR' ? dayAbs : null}
                format={inrPaise} // the chart's readout prints the move to the paise too
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
            <StockIndices symbol={symbol} />
          </Hero>
        </div>
      )}
      <Position symbol={symbol} pos={pos} mine={m} status={mine.status} sold={sold} price={price} onReload={loadMine} />
      {!sold && <VerdictSummary verdict={m?.verdict} onDetails={() => { setTab('details'); requestAnimationFrame(() => document.getElementById('stock-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); }} />}
      {/* The AI read and how the stock has done sit above the tabs: on every tab, not under the panel. */}
      <AiRead aiRead={aiRead} retryAi={user ? retryAi : () => askSignIn(FRESH_READ)} />
      <MarketFacts quick={quick.data} />

      {!user && ask?.symbol === symbol && <div id="sign-in" className="mb-3"><SignInCard {...ask} /></div>}
      <div id="stock-tabs" className="scroll-mt-16"><Tabs tabs={TABS} value={tab} onChange={setTab} label="Stock sections" /></div>
      <div className="mt-3 mb-3">
        {tab === 'chart' && quick.error && !closes.length ? <Empty title="No price data" body={`Could not load the price history for ${symbol}${cause(quick.error)}.`} action={<Button variant="secondary" onClick={reloadQuick}>Retry</Button>} /> : panel}
      </div>

      <div className="h-28 lg:h-20" aria-hidden="true" />
      <div className="fixed z-30 inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] lg:bottom-0 lg:left-56 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2">
        <div className="mx-auto max-w-5xl flex gap-3">
          {/* Signed out there is nothing to buy with: the bar says what it takes, not a bright Buy that leads to a sign-in. */}
          {!user ? <Button variant="secondary" className="flex-1" onClick={() => askSignIn(WATCH_OR_TRADE)}>Sign in to trade</Button> : <>
            {pos && <Button variant="danger" className="flex-1" onClick={() => setTicket({ symbol, side: 'SELL', lastPrice: price })}>Sell</Button>}
            <Button variant="gain" className="flex-1" disabled={price == null} onClick={() => setTicket({ symbol, side: 'BUY', lastPrice: price })}>{pos ? 'Buy more' : 'Buy'}</Button>
          </>}
        </div>
        {user && price == null && <p className="mx-auto max-w-5xl mt-1 text-[13px] text-[var(--text-muted)]">Buy is off until a price loads for {symbol}.</p>}
      </div>
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} onDone={loadMine} />}
    </Layout>
  );
};

export default Stock;
