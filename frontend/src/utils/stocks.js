import { bareSymbol } from './formatters.js';

/** The one URL for a stock's page. */
export const stockPath = (symbol) => `/stock/${encodeURIComponent(bareSymbol(symbol))}`;

// Recently opened stocks, per device. Storage can be blocked (private
// windows, previews): every access is guarded and an empty list is fine.
const KEY = 'neotrade.recentStocks';
const MAX = 8;

export const recentStocks = () => {
  try {
    const list = JSON.parse(localStorage.getItem(KEY) || '[]');
    return Array.isArray(list) ? list.slice(0, MAX) : [];
  } catch {
    return [];
  }
};

export const rememberStock = (symbol) => {
  try {
    const next = [symbol, ...recentStocks().filter((s) => s !== symbol)].slice(0, MAX);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage unavailable: nothing to remember
  }
};

export const clearRecentStocks = () => {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // storage unavailable
  }
};

const STOCK_TABS = ["chart", "news", "details", "events"];
export const stockTab = (id) => (id === "analysis" ? "details" : STOCK_TABS.includes(id) ? id : "chart");
