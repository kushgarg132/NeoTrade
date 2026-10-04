import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { SECTIONS, sectionActive } from './sections';

/**
 * The phone's primary navigation. Thumb-reachable, five destinations, safe-area
 * aware — the app is used one-handed during the session, and a hamburger that
 * hides the decisions queue behind a tap is the wrong affordance for that.
 */
const BottomNav = ({ pendingCount = 0 }) => {
  const { pathname } = useLocation();
  return (
  <nav
    className="lg:hidden fixed bottom-0 inset-x-0 z-40 border-t border-[var(--rule-strong)] bg-[var(--paper)]"
    style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    aria-label="Sections"
  >
    <ul className="grid grid-cols-5">
      {SECTIONS.filter((item) => item.primary).map((item) => {
        const isActive = sectionActive(item, pathname);
        return (
        <li key={item.path}>
          <NavLink
            to={item.path}
            end={item.path === '/'}
            className={() =>
              cn(
                'relative flex flex-col items-center justify-center gap-0.5 py-1.5 min-h-12 transition-colors',
                'font-[family-name:var(--font-narrow)] text-[0.625rem] font-semibold uppercase tracking-[0.1em]',
                isActive ? 'text-[var(--ink)]' : 'text-[var(--ink-faint)]'
              )
            }
          >
            {() => (
              <>
                {isActive && (
                  <span
                    aria-hidden="true"
                    className="absolute top-0 inset-x-3 h-0.5 bg-[var(--stamp)]"
                  />
                )}
                <span className="relative">
                  <item.icon className="w-5 h-5" strokeWidth={1.75} />
                  {item.counter && pendingCount > 0 && (
                    <span className="absolute -top-1.5 -right-2.5 min-w-[1rem] px-1 figure-md text-[0.5625rem] leading-4 text-center bg-[var(--stamp)] text-[var(--paper)]">
                      {pendingCount}
                    </span>
                  )}
                </span>
                {item.short || item.label}
              </>
            )}
          </NavLink>
        </li>
        );
      })}
    </ul>
  </nav>
  );
};

export default BottomNav;
