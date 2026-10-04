import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Loader2, X } from 'lucide-react';
import Layout from '../components/Layout';
import SmartSearch from '../components/dashboard/SmartSearch';
import BrokerPnl from '../components/dashboard/BrokerPnl';
import PortfolioGlance from '../components/dashboard/PortfolioGlance';
import TradeLedger from '../components/dashboard/TradeLedger';
import GuardrailAlerts from '../components/journal/GuardrailAlerts';
import IndexCard from '../components/dashboard/IndexCard';
import IndexAnalysis from '../components/dashboard/IndexAnalysis';
import { bareSymbol } from '../utils/formatters';
import Market from '../components/dashboard/Market';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import AnalysisCard from '../components/AnalysisCard';
import { Sheet, Empty, Tabs } from '../components/doc/Doc';
import { useTab } from '../hooks/useTab';
import { Button } from '../components/common/Button';
import api, { endpoints } from '../utils/api';
import { stream } from '../lib/ws';
import { useTopic } from '../hooks/useStream';

/**
 * The statement: real money only. What the user's own broker account did
 * today and this month, whether a guardrail they set has fired, and -- only
 * when a strategy is switched to live -- the real orders the engine placed.
 * Everything the engine does with practice money lives under /paper, so no
 * paper figure is ever read as the broker account's.
 *
 * Analysis streams over the socket and replaces the sheet stack when a scrip
 * is enquired on, then returns to it.
 */
const Dashboard = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const [journal, setJournal] = useState(null);
  const [journalLoading, setJournalLoading] = useState(true);
  const [journalError, setJournalError] = useState(null);
  const [liveTrades, setLiveTrades] = useState([]);
  const [portfolio, setPortfolio] = useState(null);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  const [tab, setTab] = useTab(['today', 'markets']);

  // An index opened from the index table replaces the stack the same way an
  // enquiry does; the two never show at once.
  const [indexTicker, setIndexTicker] = useState(null);
  const [indexDetail, setIndexDetail] = useState(null);
  const [indexError, setIndexError] = useState(null);

  const [enquirySymbol, setEnquirySymbol] = useState(null);

  const [quick, setQuick] = useState(null);
  const [quickLoading, setQuickLoading] = useState(false);
  const [quickError, setQuickError] = useState(null);

  const [ai, setAi] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);
  const [aiRequested, setAiRequested] = useState(false);

  const loadLiveTrades = () =>
    api
      .get(endpoints.trading.trades(null, 'live'))
      .then((res) => setLiveTrades(res.data))
      .catch(() => setLiveTrades([]));

  useEffect(() => {
    api
      .get(endpoints.journal.get)
      .then((res) => setJournal(res.data))
      .catch((err) => setJournalError(err?.response?.data?.detail || 'The journal did not respond'))
      .finally(() => setJournalLoading(false));

    loadLiveTrades();

    api
      .get(endpoints.portfolio.get)
      .then((res) => setPortfolio(res.data))
      .catch(() => setPortfolio(null))
      .finally(() => setPortfolioLoading(false));
  }, []);

  useTopic('trades', loadLiveTrades);

  // Overview (quote, fundamentals, technicals) has no LLM call and is what a
  // click should show immediately. AI Analysis (news/sentiment/thesis) makes
  // several sequential LLM calls -- requestAi() only fires it once the tab
  // is actually opened, so it's never on the critical path of opening a stock.
  const closeIndex = () => {
    setIndexTicker(null);
    setIndexDetail(null);
    setIndexError(null);
  };

  const openIndex = (ticker) => {
    setQuick(null);
    setQuickError(null);
    setIndexTicker(ticker);
    setIndexDetail(null);
    setIndexError(null);
    api
      .get(endpoints.marketIndex(ticker))
      .then((res) => setIndexDetail(res.data))
      .catch((err) => setIndexError(err?.response?.data?.detail || 'Could not load this index'));
  };

  const analyse = (raw) => {
    const symbol = bareSymbol(raw);
    closeIndex();
    setEnquirySymbol(symbol);
    setQuickLoading(true);
    setQuickError(null);
    setQuick(null);
    setAi(null);
    setAiError(null);
    setAiRequested(false);

    const request = stream.request('quick_analyze', { symbol }, (message) => {
      if (message.event === 'report') {
        setQuick(message.data);
        setQuickLoading(false);
      } else if (message.event === 'error') {
        setQuickError(message.data.detail);
        setQuickLoading(false);
      }
    });

    // The socket may not be up (first paint, a dropped connection); the HTTP
    // route is the same lookup, just without the progress.
    if (!request.ok) {
      api
        .post(endpoints.quickAnalyze(symbol))
        .then((res) => setQuick(res.data))
        .catch((err) => setQuickError(err?.response?.data?.detail || 'Could not load'))
        .finally(() => setQuickLoading(false));
    }
  };

  const requestAi = () => {
    if (aiRequested || !enquirySymbol) return;
    setAiRequested(true);
    setAiLoading(true);
    setAiError(null);

    const request = stream.request('analyze', { symbol: enquirySymbol }, (message) => {
      if (message.event === 'report') {
        setAi(message.data);
        setAiLoading(false);
      } else if (message.event === 'error') {
        setAiError(message.data.detail);
        setAiLoading(false);
      }
    });

    if (!request.ok) {
      api
        .post(endpoints.analyze(enquirySymbol))
        .then((res) => setAi(res.data))
        .catch((err) => setAiError(err?.response?.data?.detail || 'Analysis failed'))
        .finally(() => setAiLoading(false));
    }
  };

  // Arriving with a symbol or an index in hand: tapped anywhere in the app.
  useEffect(() => {
    const { symbol, index } = location.state || {};
    if (symbol || index) {
      // Tapped from far down a page; what opens prints at the top of the
      // statement, so start reading there.
      window.scrollTo(0, 0);
      if (symbol) analyse(symbol);
      else openIndex(index);
      navigate('.', { replace: true, state: {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state?.symbol, location.state?.index]);

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4">
        {location.pathname.startsWith('/research') && <SectionTabs tabs={RESEARCH_TABS} label="Research" />}
        {!quick && !quickLoading && !indexTicker && (
          <>
            <GuardrailAlerts />
            <PortfolioGlance snapshot={portfolio} loading={portfolioLoading} />
          </>
        )}

        <Sheet bodyClassName="px-3 py-2.5 sm:p-4">
          <SmartSearch onSearch={analyse} isLoading={quickLoading} />
        </Sheet>

        {quickLoading && (
          <Sheet title="Enquiry in progress">
            <div className="flex items-center gap-3 py-6 justify-center text-[var(--ink-soft)]">
              <Loader2 className="w-4 h-4 animate-spin text-[var(--stamp)]" />
              <span className="text-sm">Reading fundamentals and technicals…</span>
            </div>
          </Sheet>
        )}

        {quickError && (
          <Sheet
            title="Enquiry failed"
            actions={
              <button
                type="button"
                onClick={() => setQuickError(null)}
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

        {quick && !quickLoading && (
          <div className="space-y-4">
            <div className="flex justify-end">
              <Button variant="ghost" size="sm" onClick={() => setQuick(null)}>
                Back to statement
              </Button>
            </div>
            <AnalysisCard
              quick={quick}
              ai={ai}
              aiLoading={aiLoading}
              aiError={aiError}
              aiRequested={aiRequested}
              onOpenAiTab={requestAi}
            />
          </div>
        )}

        {indexTicker && (
          <div className="space-y-4">
            <div className="flex justify-end">
              <Button variant="ghost" size="sm" onClick={closeIndex}>
                Back to statement
              </Button>
            </div>
            <IndexCard detail={indexDetail} loading={!indexDetail && !indexError} error={indexError} />
            <IndexAnalysis key={indexTicker} ticker={indexTicker} />
          </div>
        )}

        {!quick && !quickLoading && !indexTicker && (
          <div>
            <Tabs
              tabs={[
                { id: 'today', label: 'Your broker' },
                { id: 'markets', label: 'Markets' },
              ]}
              active={tab}
              onSelect={setTab}
              label="Statement sections"
            />
            <div className="pt-3 sm:pt-4 space-y-3 sm:space-y-4">
              {tab === 'today' && (
                <>
                  <BrokerPnl journal={journal} loading={journalLoading} error={journalError} />
                  {/* Real orders a live strategy placed. Absent unless one exists,
                      because most accounts never switch a strategy live. */}
                  {liveTrades.length > 0 && (
                    <div className="private">
                      <TradeLedger title="Live engine orders" trades={liveTrades} loading={false} error={null} />
                    </div>
                  )}
                </>
              )}
              {tab === 'markets' && <Market />}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
};

export default Dashboard;
