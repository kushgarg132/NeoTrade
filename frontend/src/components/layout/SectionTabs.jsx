import React from 'react';
import { NavLink } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { usePendingCount } from '../../context/pendingContext';
import { useAuth } from '../../context/AuthContext';

/** The tabs inside a section (e.g. Mine: Holdings · Trades · Habits). Each tab
    is its own route, so Back and deep links work. */
const SectionTabs = ({ tabs, label }) => {
  const pending = usePendingCount();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  return (
  <nav aria-label={label} className="flex gap-1 overflow-x-auto border-b border-[var(--border)] -mx-1 px-1">
    {tabs.filter((tab) => !tab.admin || isAdmin).map((tab) => (
      <NavLink
        key={tab.to}
        to={tab.to}
        end={tab.end}
        className={({ isActive }) =>
          cn(
            // Five tabs fit a 390px phone at this size; wider screens get the roomier label.
            'shrink-0 px-2 sm:px-3 min-h-11 sm:min-h-9 flex items-center border-b-2 -mb-px transition-colors',
            'font-[family-name:var(--font-narrow)] text-[12px] sm:text-xs font-semibold',
            isActive ? 'border-[var(--accent)] text-[var(--text)]' : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text)]',
          )
        }
      >
        {tab.label}
        {tab.counter && pending > 0 && (
          <span className="ml-1.5 figure-md px-1 text-[12px] leading-4 bg-[var(--accent)] text-[var(--surface)]">{pending}</span>
        )}
      </NavLink>
    ))}
  </nav>
  );
};

export default SectionTabs;
