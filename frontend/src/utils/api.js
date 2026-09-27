import axios from 'axios';

// In production this must be same-origin (relative), not the backend's own
// nip.io host: the refresh-token cookie is SameSite=None, which browsers
// treat as third-party (and Safari/Firefox block by default) when the page
// origin and the request origin differ. Routing through vercel.json's
// /api/:path* rewrite keeps the browser talking to its own origin while
// Vercel proxies the request server-side, making the cookie first-party.
// (The WebSocket in lib/ws.js is exempt -- it authenticates via a query-param
// token, not this cookie, and still connects straight to VITE_API_URL since
// Vercel rewrites don't proxy WebSocket upgrades to an external host.)
let baseUrl;
if (import.meta.env.PROD) {
  baseUrl = '/api/v1';
} else {
  baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8001/api/v1';
  baseUrl = baseUrl.replace(/\/$/, "");
  if (!baseUrl.endsWith('/api/v1')) {
    baseUrl = `${baseUrl}/api/v1`;
  }
}

const API_BASE_URL = baseUrl;

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  // The refresh token rides in an httpOnly cookie -- the browser only
  // attaches/accepts it on a request made with credentials, cross-site
  // (Vercel -> nip.io) included.
  withCredentials: true,
});

const TOKEN_STORAGE_KEY = 'neotrade_token';

// Requests that must never trigger a refresh attempt on failure: refreshing
// itself would recurse, and a failed Google login is a real login failure,
// not an expired session to silently paper over.
const NO_REFRESH_PATHS = ['/auth/google', '/auth/refresh'];

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY);
  if (token && !NO_REFRESH_PATHS.includes(config.url)) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * At most one refresh in flight at a time -- several requests can 401
 * together (e.g. the dashboard's parallel fetch-on-mount), and they all
 * await the same attempt rather than each spending the refresh cookie's one
 * rotation.
 */
let refreshPromise = null;

export const refreshAccessToken = async () => {
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_BASE_URL}/auth/refresh`, {}, { withCredentials: true })
      .then((res) => {
        localStorage.setItem(TOKEN_STORAGE_KEY, res.data.token);
        return res.data.token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
};

const hardLogout = () => {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  if (window.location.pathname !== '/login') {
    window.location.assign('/login');
  }
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    const status = response?.status;
    const isAuthFailure = status === 401 || status === 403;
    const eligibleForRefresh = config && !NO_REFRESH_PATHS.includes(config.url) && !config._retriedAfterRefresh;

    if (isAuthFailure && eligibleForRefresh) {
      try {
        const newToken = await refreshAccessToken();
        config._retriedAfterRefresh = true;
        config.headers.Authorization = `Bearer ${newToken}`;
        return api.request(config);
      } catch {
        hardLogout();
        return Promise.reject(error);
      }
    }

    if (isAuthFailure) {
      hardLogout();
    }
    return Promise.reject(error);
  }
);

export const AUTH_TOKEN_STORAGE_KEY = TOKEN_STORAGE_KEY;

/**
 * The engine keeps two books: `paper` (practice money, the Paper tab) and
 * `live` (real orders a live strategy sent to the broker). Every ledger read
 * names one, so the two never print on the same page by accident.
 */
const inBook = (path, venue) =>
  venue ? `${path}${path.includes('?') ? '&' : '?'}venue=${venue}` : path;

export const endpoints = {
  analyze: (symbol) => `/agents/analyze/${symbol}`,
  quickAnalyze: (symbol) => `/agents/quick-analyze/${symbol}`,
  scanner: '/scanner/bullish',
  stockInfo: (symbol) => `/stock_info/${symbol}`,
  marketIndices: '/market/indices',
  trendingStocks: '/market/trending',
  // The backend derives the owner from the session token; there is no user
  // id in these paths any more.
  watchlist: {
    get: '/watchlist',
    add: (symbol) => `/watchlist/add?symbol=${encodeURIComponent(symbol)}`,
    remove: (symbol) => `/watchlist/remove/${encodeURIComponent(symbol)}`,
    details: '/watchlist/details',
  },
  globalIndices: '/market/global',
  marketIndex: (ticker) => `/market/index/${encodeURIComponent(ticker)}`,
  marketIndexAnalysis: (ticker) => `/market/index/${encodeURIComponent(ticker)}/analysis`,
  options: {
    expiries: (underlying) => `/options/expiries?underlying=${underlying}`,
    chain: (underlying, expiry) => `/options/chain?underlying=${underlying}&expiry=${expiry}`,
  },
  marketNews: '/news/market',
  trading: {
    start: '/trading/start',
    stop: '/trading/stop',
    runs: '/trading/runs',
    positions: (venue) => inBook('/trading/positions', venue),
    fills: (venue) => inBook('/trading/fills', venue),
    equity: (venue) => inBook('/trading/equity', venue),
    killSwitch: '/trading/kill-switch',
    trades: (status, venue) =>
      inBook(status ? `/trading/trades?status=${status}` : '/trading/trades', venue),
    instruments: (q) => `/trading/instruments?q=${encodeURIComponent(q)}`,
  },
  suggestions: {
    list: (params = {}) => {
      const query = new URLSearchParams(
        Object.entries(params).filter(([, value]) => value)
      ).toString();
      return query ? `/suggestions?${query}` : '/suggestions';
    },
    approve: (id) => `/suggestions/${id}/approve`,
    reject: (id) => `/suggestions/${id}/reject`,
    scan: '/suggestions/scan',
  },
  analytics: {
    pnl: (venue) => inBook('/analytics/pnl', venue),
    scorecard: (venue) => inBook('/analytics/scorecard', venue),
  },
  guardrails: {
    status: '/guardrails',
    link: '/guardrails/telegram/link',
    verify: '/guardrails/telegram/verify',
    telegram: '/guardrails/telegram',
  },
  journal: {
    get: '/journal',
    sync: '/journal/sync',
    importConsole: '/journal/import/zerodha-console',
    note: (id) => `/journal/round-trips/${encodeURIComponent(id)}/note`,
    betaMetrics: '/journal/beta-metrics',
  },
  broker: {
    list: '/broker/list',
    status: (broker) => `/broker/${broker}/status`,
    loginUrl: (broker) => `/broker/${broker}/login-url`,
    connect: (broker) => `/broker/${broker}/connect`,
    disconnect: (broker) => `/broker/${broker}/disconnect`,
  },
  settings: {
    omnirouteModels: '/settings/omniroute-models',
    omnirouteModel: '/settings/omniroute-model',
    preferences: '/settings/preferences',
    strategies: '/settings/strategies',
    promotion: '/settings/strategies/promotion',
    brokerCredentials: '/settings/broker-credentials',
  },
  auth: {
    google: '/auth/google',
    refresh: '/auth/refresh',
    logout: '/auth/logout',
    me: '/auth/me',
  },
};

export default api;
