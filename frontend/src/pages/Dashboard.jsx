import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Loader2, X } from 'lucide-react';
import Layout from '../components/Layout';
import SmartSearch from '../components/dashboard/SmartSearch';
import IndexCard from '../components/dashboard/IndexCard';
import IndexAnalysis from '../components/dashboard/IndexAnalysis';
import { bareSymbol, formatCurrency, formatSignedPercent } from '../utils/formatters';
import Market from '../components/dashboard/Market';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import AnalysisCard from '../components/AnalysisCard';
import { Sheet, Empty } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import api, { endpoints } from '../utils/api';
import { stream } from '../lib/ws';
import { cn } from '../utils/cn';
import { clearRecentStocks, recentStocks, rememberStock, stockPath } from '../utils/stocks';

/**
 * Research. With a symbol in the URL (/research/stock/:symbol) this is that
 * stock's page: the instant snapshot, and the AI analysis only once its tab
 * is opened. Without one it is the front page: search, the stocks opened
 * recently on this device, the watchlist and the markets. The user's broker
 * statement lives on Mine → Trades, not here.
 *
 * Analysis streams over the socket; the HTTP route is the fallback.
 */

const Chip = ({ to, children }) => (
  <Link
    to={to}
    className="inline-flex items-baseline gap-2 min-h-11 sm:min-h-9 px-3 py-1.5 border border-[var(--rule-strong)] hover:border-[var(--stamp)] hover:bg-[var(--paper-sunk)] transition-colors"
  >
    {children}
  </Link>
);

const FrontPage = () => {
  const [recent, setRecent] = useState(recentStocks);
  const [watch, setWatch] = useState(null);

  useEffect(() => {
    api
      .get(endpoints.watchlist.details)
      .then((res) => setWatch(res.data))
      .catch(() => setWatch([]));
  }, []);

  return (
    <>
      {recent.length > 0 && (
        <Sheet
          title="Recent"
          actions={
            <button
              type="button"
              onClick={() => {
                clearRecentStocks();
                setRecent([]);
              }}
              className="field-label text-[var(--stamp)] hover:underline min-h-9"
            >
              Clear
            </button>
          }
        >
          <div className="flex flex-wrap gap-2">
            {recent.map((symbol) => (
              <Chip key={symbol} to={stockPath(symbol)}>
                <span className="figure-md text-sm">{symbol}</span>
              </Chip>
            ))}
          </div>
        </Sheet>
      )}

      <Sheet
        title="Watchlist"
        actions={
          <Link to="/research/watchlist" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">
            All watchlist ›
          </Link>
        }
      >
        {watch === null ? (
          <div className="h-11" />
        ) : watch.length === 0 ? (
          <p className="text-sm text-[var(--ink-soft)]">Add stocks from a stock page with Watch.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {watch.map((stock) => (
              <Chip key={stock.symbol} to={stockPath(stock.symbol)}>
                <span className="figure-md text-sm">{bareSymbol(stock.symbol)}</span>
                {stock.current_price != null && (
                  <span className="figure-md text-xs text-[var(--ink-soft)]">{formatCurrency(stock.current_price)}</span>
                )}
                {stock.day_change_percent != null && (
                  <span className={cn('figure-md text-xs', stock.day_change_percent >= 0 ? 'text-up' : 'text-down')}>
                    {formatSignedPercent(stock.day_change_percent)}
                  </span>
                )}
              </Chip>
            ))}
          </div>
        )}
      </Sheet>

      <Market />
    </>
  );
};

const Dashboard = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { symbol: routeSymbol } = useParams();
  const symbol = routeSymbol ? bareSymbol(decodeURIComponent(routeSymbol)).toUpperCase() : null;

  // An index opened from the market table replaces the front page; indices
  // have no URL of their own.
  const [indexTicker, setIndexTicker] = useState(null);
  const [indexDetail, setIndexDetail] = useState(null);
  const [indexError, setIndexError] = useState(null);

  const [quick, setQuick] = useState(null);
  const [quickLoading, setQuickLoading] = useState(false);
  const [quickError, setQuickError] = useState(null);

  const [ai, setAi] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);
  const [aiRequested, setAiRequested] = useState(false);
  // The symbol on screen now: an analysis that lands for an earlier one is dropped.
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;
  const aiRequest = useRef(null);

  const closeIndex = () => {
    setIndexTicker(null);
    setIndexDetail(null);
    setIndexError(null);
  };

  const openIndex = (ticker) => {
    setIndexTicker(ticker);
    setIndexDetail(null);
    setIndexError(null);
    api
      .get(endpoints.marketIndex(ticker))
      .then((res) => setIndexDetail(res.data))
      .catch((err) => setIndexError(err?.response?.data?.detail || 'Could not load this index'));
  };

  // Overview (quote, fundamentals, technicals) has no LLM call and is what a
  // click should show immediately; AI analysis waits for its tab.
  useEffect(() => {
    if (!symbol) return undefined;
    let current = true;
    closeIndex();
    rememberStock(symbol);
    window.scrollTo(0, 0);
    setQuickLoading(true);
    setQuickError(null);
    setQuick(null);
    setAi(null);
    setAiError(null);
    setAiLoading(false);
    setAiRequested(false);

    const request = stream.request('quick_analyze', { symbol }, (message) => {
      if (!current) return;
      if (message.event === 'report') {
        setQuick(message.data);
        setQuickLoading(false);
      } else if (message.event === 'error') {
        setQuickError(message.data.detail);
        setQuickLoading(false);
      }
    });
    if (!request.ok) {
      api
        .post(endpoints.quickAnalyze(symbol))
        .then((res) => current && setQuick(res.data))
        .catch((err) => current && setQuickError(err?.response?.data?.detail || 'Could not load'))
        .finally(() => current && setQuickLoading(false));
    }
    return () => {
      current = false;
      request.cancel();
      aiRequest.current?.cancel();
      aiRequest.current = null;
    };
  }, [symbol]);

  const requestAi = () => {
    if (aiRequested || !symbol) return;
    setAiRequested(true);
    setAiLoading(true);
    setAiError(null);
    const asked = symbol;
    const stillHere = () => symbolRef.current === asked;

    const request = stream.request('analyze', { symbol }, (message) => {
      if (!stillHere()) return;
      if (message.event === 'report') {
        setAi(message.data);
        setAiLoading(false);
      } else if (message.event === 'error') {
        setAiError(message.data.detail);
        setAiLoading(false);
      }
    });

    aiRequest.current = request;
    if (!request.ok) {
      api
        .post(endpoints.analyze(symbol))
        .then((res) => stillHere() && setAi(res.data))
        .catch((err) => stillHere() && setAiError(err?.response?.data?.detail || 'Analysis failed'))
        .finally(() => stillHere() && setAiLoading(false));
    }
  };

  // Old callers still hand over a symbol in navigation state: give it its URL.
  useEffect(() => {
    const { symbol: stateSymbol, index } = location.state || {};
    if (stateSymbol) {
      navigate(stockPath(stateSymbol), { replace: true });
    } else if (index) {
      window.scrollTo(0, 0);
      openIndex(index);
      navigate('.', { replace: true, state: {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state?.symbol, location.state?.index]);

  const open = (picked) => navigate(stockPath(picked));

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4">
        <SectionTabs tabs={RESEARCH_TABS} label="Research" />

        <Sheet bodyClassName="px-3 py-2.5 sm:p-4">
          <SmartSearch onSearch={open} isLoading={Boolean(symbol) && quickLoading} />
        </Sheet>

        {symbol && (
          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={() => navigate('/research')}>
              Back to Research
            </Button>
          </div>
        )}

        {symbol && quickLoading && (
          <Sheet title="Enquiry in progress">
            <div className="flex items-center gap-3 py-6 justify-center text-[var(--ink-soft)]">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--stamp)]" />
              <span className="text-sm">Reading fundamentals and technicals…</span>
            </div>
          </Sheet>
        )}

        {symbol && quickError && (
          <Sheet
            title="Enquiry failed"
            actions={
              <button
                type="button"
                onClick={() => navigate('/research')}
                className="inline-flex items-center justify-center min-h-11 min-w-11 sm:min-h-8 sm:min-w-8 -my-2 -mr-2 text-[var(--ink-soft)] hover:text-[var(--ink)] transition-colors"
                aria-label="Dismiss the failed enquiry"
              >
                <X className="w-4 h-4" />
              </button>
            }
          >
            <Empty
              title={quickError}
              detail="The scrip may not be in the instrument master, or the data provider is unreachable."
            />
          </Sheet>
        )}

        {symbol && quick && !quickLoading && (
          <AnalysisCard
            quick={quick}
            ai={ai}
            aiLoading={aiLoading}
            aiError={aiError}
            aiRequested={aiRequested}
            onOpenAiTab={requestAi}
          />
        )}

        {!symbol && indexTicker && (
          <div className="space-y-4">
            <div className="flex justify-end">
              <Button variant="ghost" size="sm" onClick={closeIndex}>
                Back to Research
              </Button>
            </div>
            <IndexCard detail={indexDetail} loading={!indexDetail && !indexError} error={indexError} />
            <IndexAnalysis key={indexTicker} ticker={indexTicker} />
          </div>
        )}

        {!symbol && !indexTicker && <FrontPage />}
      </div>
    </Layout>
  );
};

export default Dashboard;
