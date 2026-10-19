/** Tab sets the not-yet-rebuilt pages still render through SectionTabs. */
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
  { to: '/settings/lab/strategies', label: 'Strategies', end: true },
  { to: '/settings?tab=limits', label: 'Autopilot limits' },
  { to: '/settings/lab/options', label: 'Options' },
  { to: '/settings/lab/handbook', label: 'Handbook' },
  { to: '/settings/lab/runs', label: 'Runs' },
  { to: '/settings/lab/forward', label: 'Forward' },
  { to: '/settings/lab/backlog', label: 'Backlog' },
];
