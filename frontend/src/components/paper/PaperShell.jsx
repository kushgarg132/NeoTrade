import React from 'react';
import SectionTabs from '../layout/SectionTabs';
import { PRACTICE_TABS } from '../layout/sections';

/**
 * Practice's engine pages (Engine, Book, Setup): the strategy engine trading
 * practice money, printed as a specimen copy -- a dashed stamp band that says
 * so on every page, so a practice figure can never be read as the broker
 * account's. Decisions shares the tabs but not the band: an approval there
 * can be real money.
 *
 * Engine orders from a strategy switched to live are real money; they are
 * kept out of this section and shown on Mine -> Trades instead.
 */
const PaperShell = ({ children }) => (
  <div className="private space-y-3 sm:space-y-4">
    <SectionTabs tabs={PRACTICE_TABS} label="Practice" />
    <div className="border-2 border-dashed border-[var(--stamp)] bg-[var(--stamp-soft)]">
      <div className="flex items-baseline justify-between gap-3 px-3 py-1.5 sm:px-4 sm:pt-2.5 sm:pb-2">
        <p className="font-[family-name:var(--font-narrow)] text-xs font-bold uppercase tracking-[0.16em] text-[var(--stamp)]">
          Practice
        </p>
        <p className="doc-meta normal-case text-right">
          Practice money<span className="hidden sm:inline"> · not your broker account</span>
        </p>
      </div>
    </div>

    {children}
  </div>
);

export default PaperShell;
