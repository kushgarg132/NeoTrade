import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Sheet, Money, Ruling } from '../doc/Doc';
import { formatCurrency } from '../../utils/formatters';

/**
 * The first thing on the statement: what the long-term book is worth and what
 * its action plan says, in two lines. The plan itself lives on the Portfolio
 * page; this only names the stocks each part of it is about.
 */

/** Stocks named in bold at the start of each bullet under one plan heading. */
const planNames = (plan, heading) => {
  const section = (plan || '').split(/^###\s+/m).find((part) => part.toLowerCase().startsWith(heading));
  if (!section) return [];
  return [...section.matchAll(/^\s*[-*]\s+\*\*([^*]+)\*\*/gm)].map((m) => m[1].replace(/\s*\(.*$/, '').trim());
};

const Names = ({ label, names, tone }) =>
  names.length > 0 && (
    <p className="flex items-baseline gap-2 min-w-0">
      <span className="field-label shrink-0 w-[5.5rem]">{label}</span>
      <span className={`font-semibold text-sm truncate ${tone}`}>{names.join(' · ')}</span>
    </p>
  );

const PortfolioGlance = ({ snapshot, loading }) => {
  if (loading) {
    return (
      <Sheet title="Portfolio">
        <Ruling rows={2} />
      </Sheet>
    );
  }
  if (!snapshot) {
    return (
      <Link to="/portfolio" className="sheet flex items-center justify-between gap-3 px-3 py-3 sm:px-4 hover:bg-[var(--paper-sunk)]">
        <span>
          <span className="field-label text-[var(--ink)] block">Portfolio</span>
          <span className="text-sm text-[var(--ink-soft)]">Read your holdings from your broker</span>
        </span>
        <ArrowRight className="w-4 h-4 text-[var(--stamp)] shrink-0" />
      </Link>
    );
  }
  const sell = planNames(snapshot.plan, 'sell');
  const add = planNames(snapshot.plan, 'add');
  return (
    <Link to="/portfolio" className="private sheet block hover:bg-[var(--paper-sunk)] transition-colors" aria-label="Open the portfolio">
      <div className="flex items-center justify-between gap-3 px-3 py-2 sm:px-4 border-b border-[var(--rule)] bg-[var(--paper-sunk)]">
        <span className="field-label text-[var(--ink)]">Portfolio</span>
        <ArrowRight className="w-4 h-4 text-[var(--stamp)]" aria-hidden="true" />
      </div>
      <div className="px-3 py-3 sm:px-4 space-y-2">
        <div className="flex items-end justify-between gap-3">
          <span className="figure-lg text-[clamp(1.6rem,7.5vw,2.25rem)] truncate">{formatCurrency(snapshot.totals.value)}</span>
          <span className="text-right shrink-0">
            <span className="block"><Money value={snapshot.totals.day_change} size="sm" className="text-sm" /> <span className="doc-meta">today</span></span>
            <span className="block"><Money value={snapshot.totals.pnl_pct} percent size="sm" className="text-sm" /> <span className="doc-meta">overall</span></span>
          </span>
        </div>
        {(sell.length > 0 || add.length > 0) && (
          <div className="pt-2 border-t border-[var(--rule)] space-y-1">
            <Names label="Sell / trim" names={sell} tone="text-down" />
            <Names label="Add" names={add} tone="text-up" />
          </div>
        )}
      </div>
    </Link>
  );
};

export default PortfolioGlance;
