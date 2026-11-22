import { Home, Wallet, Lightbulb, Bot, Newspaper } from 'lucide-react';

/** The five primary destinations (phone bottom tabs, desktop side rail). `counter` names a Layout count. */
export const MAIN_TABS = [
  { icon: Home, label: 'Today', section: 'home', path: '/', counter: 'attention' },
  { icon: Wallet, label: 'Portfolio', section: 'money', path: '/money' },
  { icon: Lightbulb, label: 'Ideas', path: '/ideas', counter: 'pending' },
  { icon: Bot, label: 'AI', path: '/ai' },
  { icon: Newspaper, label: 'Market', path: '/market' },
];

/** Ideas (engine suggestions and Picks) are admin-only, so everyone else sees four tabs. */
export const tabsFor = (isAdmin) => MAIN_TABS.filter((t) => isAdmin || t.path !== '/ideas');

export const tabActive = (item, pathname) =>
  item.path === '/' ? pathname === '/' : pathname === item.path || pathname.startsWith(`${item.path}/`) || (item.path === '/market' && pathname.startsWith('/news/'));

/** The main section a path belongs to, for its colour (index.css `[data-section]`): the active tab's, else
 *  Home's (stock pages, settings and the rest open from anywhere). */
// `section` keeps the CSS name (index.css `[data-section]`) when a tab's label changed.
export const sectionOf = (pathname) => {
  const t = MAIN_TABS.find((x) => tabActive(x, pathname));
  return (t?.section || t?.label || 'home').toLowerCase();
};
