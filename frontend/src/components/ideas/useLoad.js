import { useCallback, useEffect, useState } from 'react';

/** Run an async loader: { data, error, loading, reload }. A failure stays in this section only. */
export const useLoad = (fn) => {
  const [s, setS] = useState({ data: null, error: false, loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    fn().then((data) => live && setS({ data, error: false, loading: false }))
      .catch(() => live && setS({ data: null, error: true, loading: false }));
    return () => { live = false; };
  }, [fn, n]);
  const reload = useCallback(() => { setS((p) => ({ ...p, loading: true, error: false })); setN((x) => x + 1); }, []);
  return { ...s, reload };
};
