import { useCallback, useEffect, useState } from 'react';

/** Run an async loader: { data, error, loading, reload }. A failure stays in this section only. */
export const useLoad = (fn) => {
  // Each result remembers its loader: when fn changes (another week, id) the old data reads as loading, not as the new answer.
  const [raw, setS] = useState({ fn, data: null, error: false, loading: true });
  const s = raw.fn === fn ? raw : { data: null, error: false, loading: true };
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    fn().then((data) => live && setS({ fn, data, error: false, loading: false }))
      .catch(() => live && setS({ fn, data: null, error: true, loading: false }));
    return () => { live = false; };
  }, [fn, n]);
  const reload = useCallback(() => { setS((p) => ({ ...p, loading: true, error: false })); setN((x) => x + 1); }, []);
  return { data: s.data, error: s.error, loading: s.loading, reload };
};
