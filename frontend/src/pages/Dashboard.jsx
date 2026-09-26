import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import { ArrowRight, Loader2 } from 'lucide-react';
import Layout from '../components/Layout';
import SmartSearch from '../components/dashboard/SmartSearch';
import PnlStatement from '../components/dashboard/PnlStatement';
import TradeLedger from '../components/dashboard/TradeLedger';
import Market from '../components/dashboard/Market';
import AnalysisCard from '../components/AnalysisCard';
import { Sheet, Empty } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import api, { endpoints } from '../utils/api';
import { stream } from '../lib/ws';
import { useTopic } from '../hooks/useStream';

/**
 * The statement. Everything the operator checks in a mid-session glance, in
 * the order they check it: what is my net, is anything waiting for me, what
 * am I holding.
 *
 * Analysis streams over the socket and replaces the sheet stack when a scrip
 * is enquired on, then returns to it.
 */
const Dashboard = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const [pnl, setPnl] = useState(null);
  const [pnlLoading, setPnlLoading] = useState(true);
  const [trades, setTrades] = useState([]);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [tradesError, setTradesError] = useState(null);
  const [pending, setPending] = useState([]);

  const [enquirySymbol, setEnquirySymbol] = useState(null);

  const [quick, setQuick] = useState(null);
  const [quickLoading, setQuickLoading] = useState(false);
  const [quickError, setQuickError] = useState(null);

  const [ai, setAi] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);
  const [aiRequested, setAiRequested] = useState(false);

  useEffect(() => {
    api
      .get(endpoints.analytics.pnl)
      .then((res) => setPnl(res.data))
      .catch(() => setPnl(null))
      .finally(() => setPnlLoading(false));

    api
      .get(endpoints.trading.trades())
      .then((res) => setTrades(res.data))
      .catch((err) => setTradesError(err?.response?.data?.detail || 'Could not reach the ledger'))
      .finally(() => setTradesLoading(false));

    api
      .get(endpoints.suggestions.list({ status: 'PENDING' }))
      .then((res) => setPending(res.data))
      .catch(() => setPending([]));
  }, []);

  // Live: the whole point is that none of this needs a refresh.
  useTopic('pnl', (message) => setPnl(message.data));
  useTopic('trades', () => {
    api
      .get(endpoints.trading.trades())
      .then((res) => setTrades(res.data))
      .catch(() => {});
  });
  useTopic('suggestions', (message) => {
    if (message.event === 'created') setPending((list) => [message.data, ...list]);
    if (message.event === 'decided') {
      setPending((list) => list.filter((item) => item.id !== message.data.id));
    }
  });

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
            {pending.length > 0 && (
              <Link
                to="/suggestions"
                className="block sheet px-4 py-3.5 border-[var(--stamp)] hover:bg-[var(--stamp-soft)] transition-colors"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="field-label text-[var(--stamp)]">Awaiting your decision</p>
                    <p className="mt-1 text-sm text-[var(--ink)] truncate">
                      {pending.length} {pending.length === 1 ? 'proposal' : 'proposals'} ·{' '}
                      {pending
                        .slice(0, 3)
                        .map((item) => item.symbol)
                        .join(', ')}
                      {pending.length > 3 && ` +${pending.length - 3}`}
                    </p>
                  </div>
                  <ArrowRight className="w-5 h-5 shrink-0 text-[var(--stamp)]" />
                </div>
              </Link>
            )}

            <PnlStatement pnl={pnl} loading={pnlLoading} />

            <TradeLedger trades={trades} loading={tradesLoading} error={tradesError} />

            <Market />
          </>
        )}
      </div>
    </Layout>
  );
};

export default Dashboard;
