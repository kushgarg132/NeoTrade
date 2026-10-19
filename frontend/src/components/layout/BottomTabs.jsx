import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { MAIN_TABS, tabActive } from './tabs';

/** Phone navigation: five tabs, thumb-reachable, safe-area aware. */
const BottomTabs = ({ counts = {} }) => {
  const { pathname } = useLocation();
  return (
    <nav
      className="lg:hidden fixed bottom-0 inset-x-0 z-40 border-t border-[var(--border)] bg-[var(--surface)]"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      aria-label="Main"
    >
      <ul className="grid grid-cols-5">
        {MAIN_TABS.map((item) => {
          const on = tabActive(item, pathname);
          const n = counts[item.counter] || 0;
          return (
            <li key={item.path}>
              <NavLink
                to={item.path}
                end={item.path === '/'}
                aria-current={on ? 'page' : undefined}
                className={cn(
                  'flex flex-col items-center justify-center gap-0.5 min-h-14 text-[12px] font-medium',
                  on ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]',
                )}
              >
                <span className="relative">
                  <item.icon className="w-6 h-6" strokeWidth={on ? 2.25 : 1.75} aria-hidden="true" />
                  {n > 0 && (
                    <span className="absolute -top-1.5 -right-2.5 min-w-4 px-1 rounded-full bg-[var(--loss)] text-[var(--surface)] text-[12px] leading-4 text-center tabular-nums">
                      {n}
                    </span>
                  )}
                </span>
                {item.label}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};

export default BottomTabs;
