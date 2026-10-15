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
 * Re-fetch when any of `topics` fires, and after a reconnect. A burst (one
 * fill pushes `trades` and `positions` together) collapses into one fetch.
 */
export function useRefetchOn(topics, refetch, delayMs = 400) {
  const latest = useRef(refetch);
  useLayoutEffect(() => {
    latest.current = refetch;
  });
  const key = topics.join(',');
  useEffect(() => {
    let timer = null;
    const fire = () => {
      clearTimeout(timer);
      timer = setTimeout(() => latest.current(), delayMs);
    };
    const offs = key.split(',').filter(Boolean).map((topic) => stream.subscribe(topic, fire));
    offs.push(stream.onReconnect(fire));
    return () => {
      clearTimeout(timer);
      offs.forEach((off) => off());
    };
  }, [key, delayMs]);
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
