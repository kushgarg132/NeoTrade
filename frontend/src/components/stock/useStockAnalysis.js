import { useCallback, useEffect, useRef, useState } from 'react';
import api, { endpoints } from '../../utils/api';
import { stream } from '../../lib/ws';
import { rememberStock } from '../../utils/stocks';

/**
 * The instant snapshot (quote, fundamentals, technicals: no LLM call) and the AI analysis, which only
 * starts once `requestAi()` is called (the Analysis tab). Both stream over the socket; the HTTP route is
 * the fallback. Moved here from the old Dashboard `StockAnalysis`.
 */
const useStockAnalysis = (symbol) => {
  const [quick, setQuick] = useState({ data: null, loading: true, error: null });
  const [ai, setAi] = useState({ data: null, loading: false, error: null, requested: false });
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;
  const aiRequest = useRef(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!symbol) return undefined;
    let current = true;
    rememberStock(symbol);
    setQuick({ data: null, loading: true, error: null });
    setAi({ data: null, loading: false, error: null, requested: false });

    const request = stream.request('quick_analyze', { symbol }, (message) => {
      if (!current) return;
      if (message.event === 'report') setQuick({ data: message.data, loading: false, error: null });
      else if (message.event === 'error') setQuick({ data: null, loading: false, error: message.data.detail });
    });
    if (!request.ok) {
      api
        .post(endpoints.quickAnalyze(symbol))
        .then((res) => current && setQuick({ data: res.data, loading: false, error: null }))
        .catch((err) => current && setQuick({ data: null, loading: false, error: err?.response?.data?.detail || 'Could not load' }));
    }
    return () => {
      current = false;
      request.cancel();
      aiRequest.current?.cancel();
      aiRequest.current = null;
    };
  }, [symbol, retry]);

  const requestAi = useCallback(() => {
    if (!symbol) return;
    setAi({ data: null, loading: true, error: null, requested: true });
    const stillHere = () => symbolRef.current === symbol;
    const request = stream.request('analyze', { symbol }, (message) => {
      if (!stillHere()) return;
      if (message.event === 'report') setAi({ data: message.data, loading: false, error: null, requested: true });
      else if (message.event === 'error') setAi({ data: null, loading: false, error: message.data.detail, requested: true });
    });
    aiRequest.current = request;
    if (!request.ok) {
      api
        .post(endpoints.analyze(symbol))
        .then((res) => stillHere() && setAi({ data: res.data, loading: false, error: null, requested: true }))
        .catch((err) => stillHere() && setAi({ data: null, loading: false, error: err?.response?.data?.detail || 'Analysis failed', requested: true }));
    }
  }, [symbol]);

  return { quick, ai, requestAi, reloadQuick: () => setRetry((n) => n + 1) };
};

export default useStockAnalysis;
