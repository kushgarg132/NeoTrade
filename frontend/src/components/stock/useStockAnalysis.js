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
  // Each state remembers its symbol: another stock's answer reads as the initial state, no reset effect needed.
  const QUICK0 = { data: null, loading: true, error: null };
  const AI0 = { data: null, loading: false, error: null, requested: false };
  const [quickRaw, setQuick] = useState({ ...QUICK0, symbol });
  const [aiRaw, setAi] = useState({ ...AI0, symbol });
  const quick = quickRaw.symbol === symbol ? quickRaw : QUICK0;
  const ai = aiRaw.symbol === symbol ? aiRaw : AI0;
  const symbolRef = useRef(symbol);
  useEffect(() => { symbolRef.current = symbol; }, [symbol]);
  const aiRequest = useRef(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (!symbol) return undefined;
    let current = true;
    rememberStock(symbol);

    const request = stream.request('quick_analyze', { symbol }, (message) => {
      if (!current) return;
      if (message.event === 'report') setQuick({ data: message.data, loading: false, error: null, symbol });
      else if (message.event === 'error') setQuick({ data: null, loading: false, error: message.data.detail, symbol });
    });
    if (!request.ok) {
      api
        .post(endpoints.quickAnalyze(symbol))
        .then((res) => current && setQuick({ data: res.data, loading: false, error: null, symbol }))
        .catch((err) => current && setQuick({ data: null, loading: false, error: err?.response?.data?.detail || 'Could not load', symbol }));
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
    setAi({ data: null, loading: true, error: null, requested: true, symbol });
    const stillHere = () => symbolRef.current === symbol;
    const request = stream.request('analyze', { symbol }, (message) => {
      if (!stillHere()) return;
      if (message.event === 'report') setAi({ data: message.data, loading: false, error: null, requested: true, symbol });
      else if (message.event === 'error') setAi({ data: null, loading: false, error: message.data.detail, requested: true, symbol });
    });
    aiRequest.current = request;
    if (!request.ok) {
      api
        .post(endpoints.analyze(symbol))
        .then((res) => stillHere() && setAi({ data: res.data, loading: false, error: null, requested: true, symbol }))
        .catch((err) => stillHere() && setAi({ data: null, loading: false, error: err?.response?.data?.detail || 'Analysis failed', requested: true, symbol }));
    }
  }, [symbol]);

  return { quick, ai, requestAi, reloadQuick: () => { setQuick({ ...QUICK0, symbol }); setRetry((n) => n + 1); } };
};

export default useStockAnalysis;
