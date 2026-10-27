import { Home, Wallet, Lightbulb, Bot, Newspaper } from 'lucide-react';

/** The five primary destinations (phone bottom tabs, desktop side rail). `counter` names a Layout count. */
export const MAIN_TABS = [
  { icon: Home, label: 'Home', path: '/', counter: 'attention' },
  { icon: Wallet, label: 'Money', path: '/money' },
  { icon: Lightbulb, label: 'Ideas', path: '/ideas', counter: 'pending' },
  { icon: Bot, label: 'AI', path: '/ai' },
  { icon: Newspaper, label: 'Market', path: '/market' },
];

/** Ideas (engine suggestions and Picks) are admin-only, so everyone else sees four tabs. */
export const tabsFor = (isAdmin) => MAIN_TABS.filter((t) => isAdmin || t.path !== '/ideas');

export const tabActive = (item, pathname) =>
  item.path === '/' ? pathname === '/' : pathname === item.path || pathname.startsWith(`${item.path}/`) || (item.path === '/market' && pathname.startsWith('/news/'));
