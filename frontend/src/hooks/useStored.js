import { useCallback, useEffect, useState } from 'react';
import api from '../utils/api';
import useLivePoll from './useLivePoll';

/**
 * Reads text the server already stored (no model call on open). status: loading | ok | empty (404) | error.
 * `url` null waits; changing it reloads. With `liveMs` it re-reads in session; a failed re-read keeps what is shown.
 */
const useStored = (url, { liveMs } = {}) => {
  const [state, setState] = useState({ url, data: null, status: 'loading' });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!url) return undefined;
    let live = true;
    api.get(url)
      .then((r) => live && setState({ url, data: r.data, status: 'ok' }))
      .catch((e) => live && setState({ url, data: null, code: e?.response?.status, status: e?.response?.status === 404 ? 'empty' : 'error' }));
    return () => { live = false; };
  }, [url, tick]);
  const retry = useCallback(() => { setState({ url, data: null, status: 'loading' }); setTick((t) => t + 1); }, [url]);
  useLivePoll(() => (liveMs && url
    ? api.get(url).then((r) => setState((s) => (s.url === url ? { url, data: r.data, status: 'ok' } : s))).catch(() => {})
    : undefined), liveMs || 60_000);
  return { ...(state.url === url ? state : { data: null, status: 'loading' }), retry };
};


export default useStored;
