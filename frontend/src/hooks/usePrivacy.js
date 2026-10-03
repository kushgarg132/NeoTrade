import { useSyncExternalStore } from 'react';

/**
 * Hide amounts: blurs every figure inside a `.private` region (the user's own
 * money -- portfolio, broker P&L, journal, paper book) for when someone can
 * see the screen. Market data stays readable. Remembered per device; the
 * flag lives on <html data-private> so the CSS rule needs no re-render.
 */
const KEY = 'neotrade_private';
const listeners = new Set();

const read = () => {
  try {
    return localStorage.getItem(KEY) === 'on';
  } catch {
    return false;
  }
};

const apply = (on) => {
  document.documentElement.dataset.private = on ? 'on' : 'off';
};

apply(read());

export const togglePrivacy = () => {
  const next = !read();
  try {
    localStorage.setItem(KEY, next ? 'on' : 'off');
  } catch {
    // Private browsing without storage: the switch still works for this page.
  }
  apply(next);
  listeners.forEach((listener) => listener());
};

const subscribe = (listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const usePrivacy = () => useSyncExternalStore(subscribe, () => document.documentElement.dataset.private === 'on');
