import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { stream } from '../lib/ws';

/** Subscribe to one live topic for as long as a component is mounted. */
export function useTopic(topic, handler) {
  // Subscribed once per topic -- callers pass an inline function, and
  // re-subscribing on every render would thrash the socket -- but each
  // message goes to the latest handler, so it never sees stale state.
  const latest = useRef(handler);
  useLayoutEffect(() => {
    latest.current = handler;
  });
  useEffect(() => {
    if (!topic) return undefined;
    return stream.subscribe(topic, (message) => latest.current(message));
  }, [topic]);
}

/**
 * Re-fetch after the socket reconnects: pushes sent while it was down are
 * gone, so a page that only listens would show stale figures as live.
 */
export function useReconnect(refetch) {
  const latest = useRef(refetch);
  useLayoutEffect(() => {
    latest.current = refetch;
  });
  useEffect(() => stream.onReconnect(() => latest.current()), []);
}

/**
 * Whether what the user is reading is actually current.
 *
 * PRODUCT.md is explicit that a stale number presented as live is this app's
 * worst failure, so the status is surfaced rather than hidden behind an
 * optimistic reconnect.
 */
export function useStreamStatus() {
  const [status, setStatus] = useState(stream.status);
  useEffect(() => stream.onStatus(setStatus), []);
  return status;
}

/**
 * HTTP for the first paint, the socket for every update after it.
 *
 * The fetch is what makes a page correct on load; the topic is what keeps it
 * correct without a refresh.
 */
export function useLive(fetcher, topic, reducer, initial) {
  const [value, setValue] = useState(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetcher()
      .then((data) => {
        if (!cancelled) {
          setValue(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err?.response?.data?.detail || 'Could not load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useTopic(topic, (message) => {
    setValue((current) => (reducer ? reducer(current, message) : message.data));
  });

  return { value, setValue, loading, error };
}
