/** Every real route path, and the old paths that redirect to them in one hop. */
export const LAB_PAGES = ['strategies', 'options', 'runs', 'forward', 'handbook', 'backlog'];

export const ROUTES = [
  '/', '/money', '/ideas', '/ideas/history', '/ideas/:id', '/ai', '/market', '/stock/:symbol',
  '/settings', ...LAB_PAGES.map((p) => `/settings/lab/${p}`), '/reports/weekly', '/login', '/profile',
];

/** The Lab is admin only (RequireAdmin in App.jsx). */
export const ADMIN_ROUTES = LAB_PAGES.map((p) => `/settings/lab/${p}`);

const LAB = '/settings/lab/strategies';
const LIMITS = '/settings?tab=limits';

/** [from, to]: the query string is kept by `Moved`. A `to` is always a real route. */
export const MOVED = [
  ['/portfolio', '/money'], ['/portfolio/holdings', '/money?tab=holdings'], ['/portfolio/tax', '/money?tab=tax'],
  ['/portfolio/import', '/money?tab=holdings'], ['/portfolio/news', '/market?tab=news'],
  ['/portfolio/watchlist', '/market?tab=watchlist'], ['/journal', '/money?tab=journal'], ['/picks', '/ideas'],
  ['/ai/book', '/ai?tab=positions'], ['/ai/activity', '/ai?tab=activity'],
  ['/lab', LAB], ['/lab/limits', LIMITS],
  ...['options', 'runs', 'forward', 'handbook', 'backlog'].map((p) => [`/lab/${p}`, `/settings/lab/${p}`]),
  ['/mine', '/money'], ['/mine/holdings', '/money?tab=holdings'], ['/mine/tax', '/money?tab=tax'],
  ['/mine/journal', '/money?tab=journal'], ['/mine/trades', '/money?tab=journal'],
  ['/mine/habits', '/money?tab=journal&jtab=habits'], ['/mine/ideas', '/money'],
  ['/research', '/'], ['/scanner', '/'], ['/research/scanner', '/'],
  ['/research/news', '/market?tab=news'], ['/research/watchlist', '/market?tab=watchlist'], ['/watchlist', '/market?tab=watchlist'],
  ['/research/picks', '/ideas'], ['/research/options', '/settings/lab/options'], ['/options', '/settings/lab/options'],
  ['/import', '/money?tab=holdings'], ['/system', '/settings/lab/handbook'], ['/system/future', '/settings/lab/backlog'],
  ['/ai/strategies', LAB], ['/ai/settings', LIMITS], ['/ai/autopilot', LIMITS], ['/ai/limits', LIMITS],
  ['/ai/decisions', '/money'],
  ['/practice', '/ai'], ['/practice/book', '/ai?tab=positions'], ['/practice/strategies', LAB],
  ['/practice/setup', LIMITS], ['/practice/decisions', '/money'], ['/practice/library', LAB],
  ['/ai/practice', '/ai'], ['/ai/practice/decisions', '/money'], ['/ai/practice/book', '/ai?tab=positions'],
  ['/ai/practice/holdings', '/ai?tab=positions'], ['/ai/practice/engine', '/ai'], ['/ai/practice/settings', LIMITS],
  ['/decisions', '/money'], ['/suggestions', '/money'], ['/paper', '/ai'], ['/paper/decisions', '/money'],
  ['/paper/holdings', '/ai?tab=positions'], ['/paper/engine', '/ai'], ['/paper/settings', LIMITS], ['/trading', '/ai'],
];

/** `to` plus the old URL's query; if `to` already has one, merge with `&` (the old URL's value wins). */
export const withSearch = (to, search) => {
  if (!search) return to;
  const [path, q = ''] = to.split('?');
  const merged = new URLSearchParams(q);
  new URLSearchParams(search).forEach((v, k) => merged.set(k, v));
  return `${path}?${merged}`;
};

/** Where an old URL goes. The old Journal's own `?tab=` (habits, guardrails) is now `?jtab=`. */
export const movedTarget = (from, to, search) => {
  if (from !== '/journal' && from !== '/mine/journal') return withSearch(to, search);
  const q = new URLSearchParams(search);
  const old = q.get('tab');
  if (old) {
    q.delete('tab');
    q.set('jtab', old === 'patterns' || old === 'learning' ? 'habits' : old);
  }
  return withSearch(to, q.toString() ? `?${q}` : '');
};

/** Where a broker's login redirect (Upstox ?code=, Kite ?request_token=) should land when it came back to
 * some other page: Settings -> Accounts, which submits the code. Null when there is nothing to move. */
export const brokerReturnTarget = (pathname, search) => {
  const params = new URLSearchParams(search);
  if (!params.get('code') && !params.get('request_token')) return null;
  if (pathname === '/settings' && params.get('tab') === 'accounts') return null;
  params.delete('tab');
  return `/settings?tab=accounts&${params.toString()}`;
};
