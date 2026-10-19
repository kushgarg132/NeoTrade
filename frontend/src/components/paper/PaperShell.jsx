import React from 'react';
import SectionTabs from '../layout/SectionTabs';
import { AI_TABS } from '../layout/sections';

/**
 * The AI account's paper pages (Book, Strategies): what the app trades on
 * paper while no strategy has earned live money, printed as a specimen copy
 * -- a dashed stamp band on every page, so a paper figure is never read as a
 * broker account's.
 */
const PaperShell = ({ children, tabs = AI_TABS, label = 'AI account' }) => (
  <div className="private space-y-3 sm:space-y-4">
    <SectionTabs tabs={tabs} label={label} />
    <div className="border-2 border-dashed border-[var(--accent)] bg-[var(--accent-soft)]">
      <div className="flex items-baseline justify-between gap-3 px-3 py-1.5 sm:px-4 sm:pt-2.5 sm:pb-2">
        <p className="font-[family-name:var(--font-narrow)] text-xs font-bold text-[var(--accent)]">
          AI account · paper
        </p>
        <p className="doc-meta normal-case text-right">
          Paper money<span className="hidden sm:inline"> · until a strategy earns live</span>
        </p>
      </div>
    </div>

    {children}
  </div>
);

export default PaperShell;
