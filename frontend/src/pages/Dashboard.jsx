import React, { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import AnalysisCard from '../components/AnalysisCard';
import { Sheet, Empty } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { stream } from '../lib/ws';
import { rememberStock } from '../utils/stocks';

/**
 * The analysis half of the stock page (/stock/:symbol, hosted by MineStock):
 * the instant snapshot, and the AI analysis only once its tab is opened.
 * Search lives in the masthead. Analysis streams over the socket; the HTTP
 * route is the fallback.
 */
export const StockAnalysis = ({ symbol }) => {
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

  // Overview (quote, fundamentals, technicals) has no LLM call and is what a
  // click should show immediately; AI analysis waits for its tab.
  useEffect(() => {
    if (!symbol) return undefined;
    let current = true;
    rememberStock(symbol);
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

  return (
    <>
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
        <AnalysisCard
          quick={quick}
          ai={ai}
          aiLoading={aiLoading}
          aiError={aiError}
          aiRequested={aiRequested}
          onOpenAiTab={requestAi}
        />
      )}
    </>
  );
};
