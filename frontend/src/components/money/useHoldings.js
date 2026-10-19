import { useCallback, useEffect, useState } from 'react';
import api, { endpoints } from '../../utils/api';
import { useRefetchOn } from '../../hooks/useStream';
import { marketPhase } from '../../utils/formatters';

const LIVE_POLL_MS = 5_000;

/**
 * The user's own holdings snapshot. `poll` re-reads it every 5 s while NSE trades (Holdings tab);
 * a failed poll keeps what is on screen. `snapshot` is null before the first daily review (404).
 */
export default function useHoldings({ poll = false } = {}) {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    (stale = () => false) =>
      api
        .get(endpoints.portfolio.get, { params: { account: 'mine', live: true } })
        .then((res) => !stale() && setSnapshot(res.data))
        .catch(() => {})
        .finally(() => !stale() && setLoading(false)),
    []
  );

  useEffect(() => {
    let gone = false;
    let inFlight = false;
    const fetchLive = () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      load(() => gone).finally(() => { inFlight = false; });
    };
    fetchLive();
    if (!poll) return () => { gone = true; };
    const timer = setInterval(() => marketPhase() !== 'closed' && fetchLive(), LIVE_POLL_MS);
    document.addEventListener('visibilitychange', fetchLive);
    return () => {
      gone = true;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', fetchLive);
    };
  }, [load, poll]);
  useRefetchOn(['portfolio', 'trades'], () => load());

  return { snapshot, loading, reload: load };
}
