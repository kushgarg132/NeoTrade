import { useCallback, useEffect, useState } from 'react';
import useLivePoll from './useLivePoll';

/** A section that loads itself: `[{ data, error }, retry]`. With `liveMs` it re-reads in session; a failed re-read keeps the last figures (their AsOf turns stale). */
const useSection = (load, { liveMs } = {}) => {
  const [state, setState] = useState({ data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    load().then((data) => live && setState({ data, error: null })).catch(() => live && setState({ data: null, error: true }));
    return () => { live = false; };
  }, [load, tick]);
  const retry = useCallback(() => { setState({ data: null, error: null }); setTick((t) => t + 1); }, []);
  useLivePoll(() => (liveMs ? load().then((data) => setState({ data, error: null })).catch(() => {}) : undefined), liveMs || 60_000);
  return [state, retry];
};

export default useSection;
