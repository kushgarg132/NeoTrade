import { useEffect, useReducer, useState } from 'react';
import api, { endpoints } from '../../utils/api';
import { stream } from '../../lib/ws';
import { rememberStock } from '../../utils/stocks';
import { AI_EMPTY, aiReducer } from '../../utils/aiRead';

/**
 * The instant snapshot (quote, fundamentals, technicals: no LLM call) and the AI read, which starts on every
 * open: the socket sends the last read at once and streams a fresh one when it is stale. The HTTP routes are the
 * fallback when there is no socket. `{ ai: false }` skips the AI read (pages that only need the snapshot).
 */
const useStockAnalysis = (symbol, { ai: wantAi = true } = {}) => {
  // Each state remembers its symbol: another stock's answer reads as the initial state, no reset effect needed.
  const QUICK0 = { data: null, loading: true, error: null };
  const [quickRaw, setQuick] = useState({ ...QUICK0, symbol });
  const [aiState, dispatch] = useReducer(aiReducer, AI_EMPTY);
  const [aiTry, setAiTry] = useState(0);
  const quick = quickRaw.symbol === symbol ? quickRaw : QUICK0;
  const aiRead = aiState.symbol === symbol ? aiState : { ...AI_EMPTY, symbol };
  const ai = { data: aiRead.read, loading: aiRead.loading && !aiRead.read, error: aiRead.error };
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
    };
  }, [symbol, retry]);

  useEffect(() => {
    if (!symbol || !wantAi) return undefined;
    let current = true;
    const send = (event, data) => current && dispatch({ symbol, event, data });
    send('reset');
    const request = stream.request('analyze', { symbol }, (m) => {
      send(m.event, m.data);
      if (m.event === 'error') send('done');
    });
    if (!request.ok) {
      (async () => {
        let stale = true;
        try {
          const { data } = await api.get(endpoints.stockNote(symbol));
          stale = !!data.stale;
          send('cached', { read: data.read, at: data.at, stale });
        } catch { // 404 = no read yet; any other failure also falls through to a run
          send('cached', { read: null, at: null, stale: true });
        }
        if (stale) {
          try {
            send('report', (await api.post(endpoints.analyze(symbol))).data);
          } catch (err) {
            send('error', { detail: err?.response?.data?.detail || 'Analysis failed' });
          }
        }
        send('done');
      })();
    }
    return () => { current = false; request.cancel(); };
  }, [symbol, aiTry, wantAi]);

  return { quick, ai, aiRead, retryAi: () => setAiTry((n) => n + 1), reloadQuick: () => { setQuick({ ...QUICK0, symbol }); setRetry((n) => n + 1); } };
};

export default useStockAnalysis;
