import { useEffect, useRef } from 'react';
import { marketPhase } from '../utils/formatters';

/**
 * Calls `refresh` (returns a promise) every `ms` while NSE trades and the page is visible, and once whenever the page
 * comes back into view, so a phone unlocked mid-session never shows the numbers it went to sleep on. Never two at once.
 * `always`: keep the timer running outside the session too, for pages with more than prices on them.
 */
export default function useLivePoll(refresh, ms, { always = false } = {}) {
  const fn = useRef(refresh);
  useEffect(() => { fn.current = refresh; });
  useEffect(() => {
    let inFlight = false;
    const run = () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      Promise.resolve(fn.current()).finally(() => { inFlight = false; });
    };
    const timer = setInterval(() => { if (always || marketPhase() !== 'closed') run(); }, ms);
    document.addEventListener('visibilitychange', run);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', run);
    };
  }, [ms, always]);
}
