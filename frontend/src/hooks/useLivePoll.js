import { useEffect, useRef } from 'react';
import { marketPhase } from '../utils/formatters';

/** Calls `refresh` (returns a promise) every `ms` while NSE trades and the page is visible; never two at once. */
export default function useLivePoll(refresh, ms) {
  const fn = useRef(refresh);
  fn.current = refresh;
  useEffect(() => {
    let inFlight = false;
    const timer = setInterval(() => {
      if (inFlight || document.hidden || marketPhase() === 'closed') return;
      inFlight = true;
      Promise.resolve(fn.current()).finally(() => { inFlight = false; });
    }, ms);
    return () => clearInterval(timer);
  }, [ms]);
}
