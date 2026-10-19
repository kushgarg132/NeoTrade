import { useCallback, useEffect, useState } from 'react';
import api from '../utils/api';

/**
 * Reads text the server already stored (no model call on open). status: loading | ok | empty (404) | error.
 * `url` null waits; changing it reloads.
 */
const useStored = (url) => {
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
  return { ...(state.url === url ? state : { data: null, status: 'loading' }), retry };
};


export default useStored;
