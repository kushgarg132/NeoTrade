import { Sun, Wallet, Bot, Search, Settings } from 'lucide-react';

/**
 * The five sections, shared by the desktop index and the phone's bottom bar,
 * laid out around the trader's day: Today (what needs me), Mine (my own
 * account), AI (the AI account only), Research, More (Practice -- the strategy
 * engine -- plus setup).
 * `match` lists the path prefixes a section owns, so its tab stays lit on
 * every page inside it.
 */
export const SECTIONS = [
  { icon: Sun, label: 'Today', path: '/', match: ['/'], exact: true, primary: true },
  { icon: Wallet, label: 'Mine', path: '/mine/holdings', match: ['/mine'], primary: true },
  { icon: Bot, label: 'AI', path: '/ai', match: ['/ai'], primary: true },
  { icon: Search, label: 'Research', path: '/research', match: ['/research'], primary: true },
  { icon: Settings, label: 'More', path: '/settings', match: ['/settings', '/profile', '/practice', '/system'], primary: true, counter: true },
];

export const sectionActive = (item, pathname) =>
  item.exact ? pathname === '/' : item.match.some((p) => pathname === p || pathname.startsWith(`${p}/`));

export const MINE_TABS = [
  { to: '/mine/holdings', label: 'Holdings' },
  { to: '/mine/trades', label: 'Trades' },
  { to: '/mine/habits', label: 'Habits' },
];

export const AI_TABS = [
  { to: '/ai', label: 'Overview', end: true },
  { to: '/ai/activity', label: 'Activity' },
  { to: '/ai/autopilot', label: 'Autopilot' },
];

/** Practice: the strategy engine's proposals and its practice-money book. */
export const PRACTICE_TABS = [
  { to: '/practice/decisions', label: 'Decisions', counter: true },
  { to: '/practice', label: 'Engine', end: true },
  { to: '/practice/book', label: 'Book' },
  { to: '/practice/setup', label: 'Setup' },
];

export const RESEARCH_TABS = [
  { to: '/research', label: 'Search', end: true },
  { to: '/research/watchlist', label: 'Watchlist' },
  { to: '/research/scanner', label: 'Scanner' },
  { to: '/research/options', label: 'Options' },
];
