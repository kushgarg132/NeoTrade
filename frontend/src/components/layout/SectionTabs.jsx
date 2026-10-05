import React from 'react';
import { NavLink } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { usePendingCount } from '../../context/pendingContext';

/** The tabs inside a section (e.g. Mine: Holdings · Trades · Habits). Each tab
    is its own route, so Back and deep links work. */
const SectionTabs = ({ tabs, label }) => {
  const pending = usePendingCount();
  return (
  <nav aria-label={label} className="flex gap-1 overflow-x-auto border-b border-[var(--rule-strong)] -mx-1 px-1">
    {tabs.map((tab) => (
      <NavLink
        key={tab.to}
        to={tab.to}
        end={tab.end}
        className={({ isActive }) =>
          cn(
            'shrink-0 px-3 min-h-11 sm:min-h-9 flex items-center border-b-2 -mb-px transition-colors',
            'font-[family-name:var(--font-narrow)] text-xs font-semibold uppercase tracking-[0.11em]',
            isActive ? 'border-[var(--stamp)] text-[var(--ink)]' : 'border-transparent text-[var(--ink-faint)] hover:text-[var(--ink)]',
          )
        }
      >
        {tab.label}
        {tab.counter && pending > 0 && (
          <span className="ml-1.5 figure-md px-1 text-[0.5625rem] leading-4 bg-[var(--stamp)] text-[var(--paper)]">{pending}</span>
        )}
      </NavLink>
    ))}
  </nav>
  );
};

export default SectionTabs;
