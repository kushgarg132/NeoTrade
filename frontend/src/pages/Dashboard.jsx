import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import Layout from '../components/Layout';
import SmartSearch from '../components/dashboard/SmartSearch';
import BrokerPnl from '../components/dashboard/BrokerPnl';
import TradeLedger from '../components/dashboard/TradeLedger';
import GuardrailAlerts from '../components/journal/GuardrailAlerts';
import Market from '../components/dashboard/Market';
import AnalysisCard from '../components/AnalysisCard';
import { Sheet, Empty } from '../components/doc/Doc';
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
  }, []);

  useTopic('trades', loadLiveTrades);

  // Overview (quote, fundamentals, technicals) has no LLM call and is what a
  // click should show immediately. AI Analysis (news/sentiment/thesis) makes
  // several sequential LLM calls -- requestAi() only fires it once the tab
  // is actually opened, so it's never on the critical path of opening a stock.
  const analyse = (symbol) => {
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

  // Arriving with a symbol in hand: a scrip tapped anywhere in the app.
  useEffect(() => {
    if (location.state?.symbol) {
      // A scrip can be tapped from far down any page; the enquiry prints at
      // the top of the statement, so start reading there.
      window.scrollTo(0, 0);
      analyse(location.state.symbol);
      navigate('.', { replace: true, state: {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state?.symbol]);

  return (
    <Layout>
      <div className="space-y-4">
        <Sheet bodyClassName="p-4">
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
          <Sheet title="Enquiry failed">
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

        {!quick && !quickLoading && (
          <>
            <GuardrailAlerts />

            <BrokerPnl journal={journal} loading={journalLoading} error={journalError} />

            {/* Real orders a live strategy placed. Absent unless one exists,
                because most accounts never switch a strategy live. */}
            {liveTrades.length > 0 && (
              <TradeLedger title="Live engine orders" trades={liveTrades} loading={false} error={null} />
            )}

            <Market />
          </>
        )}
      </div>
    </Layout>
  );
};

export default Dashboard;
