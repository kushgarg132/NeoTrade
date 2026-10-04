import React from 'react';
import { NavLink } from 'react-router-dom';
import SectionTabs from '../layout/SectionTabs';
import { AI_TABS } from '../layout/sections';
import { cn } from '../../utils/cn';
import { usePendingCount } from '../../context/pendingContext';

/**
 * The paper book's own section. Everything under /paper is the strategy
 * engine trading practice money, and it is printed as a specimen copy:
 * a dashed stamp band that says so on every page, so a paper figure can
 * never be read as the broker account's.
 *
 * Engine orders from a strategy switched to live are real money; they are
 * kept out of this section and shown on the statement instead.
 */

const PAPER_TABS = [
  { path: '/ai/practice', label: 'Overview', end: true },
  { path: '/decisions', label: 'Decisions', short: 'Decide', counter: true },
  { path: '/ai/practice/book', label: 'Book' },
  { path: '/ai/practice/settings', label: 'Settings', short: 'Setup' },
];

const PaperShell = ({ children }) => {
  const pending = usePendingCount();

  return (
    <div className="private space-y-3 sm:space-y-4">
      <SectionTabs tabs={AI_TABS} label="AI account" />
      <div className="border-2 border-dashed border-[var(--stamp)] bg-[var(--stamp-soft)]">
        <div className="flex items-baseline justify-between gap-3 px-3 py-1.5 sm:px-4 sm:pt-2.5 sm:pb-2">
          <p className="font-[family-name:var(--font-narrow)] text-xs font-bold uppercase tracking-[0.16em] text-[var(--stamp)]">
            Paper trading
          </p>
          <p className="doc-meta normal-case text-right">
            Practice money<span className="hidden sm:inline"> · not your broker account</span>
          </p>
        </div>
        <nav
          className="grid grid-cols-4 border-t border-dashed border-[var(--stamp)]"
          aria-label="Paper trading"
        >
          {PAPER_TABS.map((tab) => (
            <NavLink
              key={tab.path}
              to={tab.path}
              end={tab.end}
              className={({ isActive }) =>
                cn(
                  'min-w-0 min-h-10 px-1 sm:px-3 inline-flex items-center justify-center gap-1 sm:gap-1.5 whitespace-nowrap border-b-2 -mb-px transition-colors',
                  'font-[family-name:var(--font-narrow)] text-[0.625rem] sm:text-[0.6875rem] font-semibold uppercase tracking-[0.04em] sm:tracking-[0.11em]',
                  isActive
                    ? 'border-[var(--stamp)] text-[var(--ink)] bg-[var(--paper)]'
                    : 'border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)]'
                )
              }
            >
              {/* A phone fits the tabs only on the short names. */}
              <span className="sm:hidden">{tab.short || tab.label}</span>
              <span className="hidden sm:inline">{tab.label}</span>
              {tab.counter && pending > 0 && (
                <span className="figure-md px-1 text-[0.5625rem] leading-4 bg-[var(--stamp)] text-[var(--paper)]">
                  {pending}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
      </div>

      {children}
    </div>
  );
};

export default PaperShell;
