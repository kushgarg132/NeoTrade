import { Sun, Wallet, Bot, Search, Settings } from 'lucide-react';

/**
 * The sections, shared by the desktop index and the phone's bottom bar,
 * around the trader's two accounts (Phase 19): Today (where am I, what do I
 * do), Mine (my own account: holdings, what needs you, tax, journal), AI (the account
 * the app runs, paper until a strategy earns live), Research, More (setup).
 * `match` lists the path prefixes a section owns, so its tab stays lit on
 * every page inside it.
 */
export const SECTIONS = [
  // Badges: Today counts what needs you outside ideas (logins, waiting
  // cards, interrupted approvals, guardrail alerts); Mine counts its Needs-you list.
  { icon: Sun, label: 'Today', path: '/', match: ['/'], exact: true, primary: true, counter: 'attention' },
  { icon: Wallet, label: 'Mine', path: '/mine', match: ['/mine'], primary: true, counter: 'pending' },
  { icon: Bot, label: 'AI', path: '/ai', match: ['/ai'], primary: true },
  { icon: Search, label: 'Research', path: '/research', match: ['/research'], primary: true },
  { icon: Settings, label: 'More', path: '/settings', match: ['/settings', '/profile', '/system'], primary: true },
];

/** The badge number for a section: `attention` for Today, ideas for Mine. */
export const sectionCount = (item, counts) => (item.counter ? counts[item.counter] || 0 : 0);

export const sectionActive = (item, pathname) =>
  item.exact ? pathname === '/' : item.match.some((p) => pathname === p || pathname.startsWith(`${p}/`));

export const MINE_TABS = [
  { to: '/mine', label: 'Overview', end: true, counter: true },
  { to: '/mine/holdings', label: 'Holdings' },
  { to: '/mine/tax', label: 'Tax' },
  { to: '/mine/journal', label: 'Journal' },
];

/** The AI account: paper until a strategy passes both gates, then live. */
export const AI_TABS = [
  { to: '/ai', label: 'Overview', end: true },
  { to: '/ai/activity', label: 'Activity' },
  { to: '/ai/book', label: 'Book' },
  { to: '/ai/strategies', label: 'Strategies' },
  { to: '/ai/settings', label: 'Settings' },
];

export const RESEARCH_TABS = [
  { to: '/research', label: 'Search', end: true },
  { to: '/research/news', label: 'News' },
  { to: '/research/watchlist', label: 'Watchlist' },
  // Admin-only until the SEBI RA registration exists (SectionTabs drops it for everyone else).
  { to: '/research/picks', label: 'Picks', admin: true },
];
