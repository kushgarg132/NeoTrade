import { useCallback, useEffect, useState } from 'react';

/** A section that loads itself: `[{ data, error }, retry]`. */
const useSection = (load) => {
  const [state, setState] = useState({ data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    load().then((data) => live && setState({ data, error: null })).catch(() => live && setState({ data: null, error: true }));
    return () => { live = false; };
  }, [load, tick]);
  const retry = useCallback(() => { setState({ data: null, error: null }); setTick((t) => t + 1); }, []);
  return [state, retry];
};

export default useSection;
