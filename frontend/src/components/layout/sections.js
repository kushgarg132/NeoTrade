import { Sun, Sparkles, Bot, Wallet, NotebookPen, FlaskConical } from 'lucide-react';

/**
 * The sections, shared by the desktop index and the phone's bottom bar (the
 * daily workstation): Today (what to do now), Picks and Lab (admin only), AI
 * (the account the app runs), Portfolio (my holdings, tax, news, watchlist),
 * Journal (trades, habits, guardrails). `match` lists the path prefixes a
 * section owns, so its tab stays lit on every page inside it.
 */
export const SECTIONS = [
  // Badges: Today counts what needs you outside ideas (logins, waiting
  // cards, interrupted approvals, guardrail alerts); Portfolio counts its Needs-you list.
  { icon: Sun, label: 'Today', path: '/', match: ['/'], exact: true, primary: true, counter: 'attention' },
  { icon: Sparkles, label: 'Picks', path: '/picks', match: ['/picks'], primary: true, admin: true },
  { icon: Bot, label: 'AI', path: '/ai', match: ['/ai'], primary: true },
  { icon: Wallet, label: 'Portfolio', path: '/portfolio', match: ['/portfolio'], primary: true, counter: 'pending' },
  { icon: NotebookPen, label: 'Journal', path: '/journal', match: ['/journal'], primary: true },
  { icon: FlaskConical, label: 'Lab', path: '/lab', match: ['/lab'], primary: true, admin: true },
];

/** The badge number for a section: `attention` for Today, ideas for Portfolio. */
export const sectionCount = (item, counts) => (item.counter ? counts[item.counter] || 0 : 0);

export const sectionActive = (item, pathname) =>
  item.exact ? pathname === '/' : item.match.some((p) => pathname === p || pathname.startsWith(`${p}/`));

export const PORTFOLIO_TABS = [
  { to: '/portfolio', label: 'Overview', end: true, counter: true },
  { to: '/portfolio/holdings', label: 'Holdings' },
  { to: '/portfolio/tax', label: 'Tax' },
  { to: '/portfolio/news', label: 'News' },
  { to: '/portfolio/watchlist', label: 'Watchlist' },
  { to: '/portfolio/import', label: 'Import' },
];

/** The AI account: paper until a strategy passes both gates, then live. */
export const AI_TABS = [
  { to: '/ai', label: 'Overview', end: true },
  { to: '/ai/activity', label: 'Activity' },
  { to: '/ai/book', label: 'Book' },
];

/** The Lab: frozen and experimental features, admin only. */
export const LAB_TABS = [
  { to: '/lab', label: 'Strategies', end: true },
  { to: '/lab/limits', label: 'Autopilot limits' },
  { to: '/lab/options', label: 'Options' },
  { to: '/lab/handbook', label: 'Handbook' },
  { to: '/lab/backlog', label: 'Backlog' },
];
