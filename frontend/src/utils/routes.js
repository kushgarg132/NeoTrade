/** Every real route path, and the old paths that redirect to them in one hop. */
export const ROUTES = [
  '/', '/portfolio', '/portfolio/holdings', '/portfolio/tax', '/portfolio/news', '/portfolio/watchlist',
  '/portfolio/import', '/journal', '/picks', '/ai', '/ai/activity', '/ai/book',
  '/lab', '/lab/limits', '/lab/options', '/lab/handbook', '/lab/runs', '/lab/forward', '/lab/backlog',
  '/stock/:symbol', '/settings', '/profile',
];

/** Picks and Lab are admin only (RequireAdmin in App.jsx; their tabs are flagged admin). */
export const ADMIN_ROUTES = ['/picks', '/lab', '/lab/limits', '/lab/options', '/lab/handbook', '/lab/runs', '/lab/forward', '/lab/backlog'];

/** [from, to]: the query string is kept by `Moved`. A `to` is always a real route. */
export const MOVED = [
  ['/mine', '/portfolio'], ['/mine/holdings', '/portfolio/holdings'], ['/mine/tax', '/portfolio/tax'],
  ['/mine/journal', '/journal'], ['/mine/trades', '/journal'], ['/mine/habits', '/journal?tab=habits'],
  ['/mine/ideas', '/portfolio'],
  ['/research', '/'], ['/scanner', '/'], ['/research/scanner', '/'],
  ['/research/news', '/portfolio/news'], ['/research/watchlist', '/portfolio/watchlist'], ['/watchlist', '/portfolio/watchlist'],
  ['/research/picks', '/picks'], ['/research/options', '/lab/options'], ['/options', '/lab/options'],
  ['/import', '/portfolio/import'], ['/system', '/lab/handbook'], ['/system/future', '/lab/backlog'],
  ['/ai/strategies', '/lab'], ['/ai/settings', '/lab/limits'], ['/ai/autopilot', '/lab/limits'], ['/ai/limits', '/lab/limits'],
  ['/ai/decisions', '/portfolio'],
  ['/practice', '/ai'], ['/practice/book', '/ai/book'], ['/practice/strategies', '/lab'],
  ['/practice/setup', '/lab/limits'], ['/practice/decisions', '/portfolio'], ['/practice/library', '/lab'],
  ['/ai/practice', '/ai'], ['/ai/practice/decisions', '/portfolio'], ['/ai/practice/book', '/ai/book'],
  ['/ai/practice/holdings', '/ai/book'], ['/ai/practice/engine', '/ai'], ['/ai/practice/settings', '/lab/limits'],
  ['/decisions', '/portfolio'], ['/suggestions', '/portfolio'], ['/paper', '/ai'], ['/paper/decisions', '/portfolio'],
  ['/paper/holdings', '/ai/book'], ['/paper/engine', '/ai'], ['/paper/settings', '/lab/limits'], ['/trading', '/ai'],
];

/** `to` plus the old URL's query; if `to` already has one, merge with `&` (the old URL's value wins). */
export const withSearch = (to, search) => {
  if (!search) return to;
  const [path, q = ''] = to.split('?');
  const merged = new URLSearchParams(q);
  new URLSearchParams(search).forEach((v, k) => merged.set(k, v));
  return `${path}?${merged}`;
};
