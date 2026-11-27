import React from 'react';
import { ChevronRight } from 'lucide-react';
import Badge from '../ui/Badge';
import { REASONS } from '../../utils/mine';
import { reasonFact } from '../../utils/verdict';
import { day, verdictKind, verdictLabel } from './common';

/**
 * The verdict's answer above the tabs: badge and since when, its first reason with that reason's figure, how often it
 * has changed, and a link to every reason on Details. Nothing without a current verdict (admin-only data).
 */
const VerdictSummary = ({ verdict: v, onDetails }) => {
  if (!v?.current) return null;
  const first = v.reasons?.[0];
  const fact = first && reasonFact(first, v.facts, v.limits);
  const more = (v.reasons?.length || 0) - 1;
  const changes = (v.history?.length || 0) - 1;
  return (
    <section aria-label="Our verdict" className="mb-3 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[15px] font-semibold text-[var(--text)]">Our verdict</span>
          <Badge kind={verdictKind(v.current)}>{verdictLabel(v.current)}</Badge>
        </div>
        {v.since && <span className="shrink-0 text-[13px] text-[var(--text-muted)]">since {day(v.since)}</span>}
      </div>
      {first && (
        <div className="mt-2">
          <p className="text-[14px] font-medium text-[var(--text)]">{REASONS[first] || first.replace(/_/g, ' ')}</p>
          {fact && <p className="private text-[13px] tabular-nums text-[var(--text-muted)]">{fact}</p>}
        </div>
      )}
      <button type="button" onClick={onDetails}
        className="-mb-1 mt-1 inline-flex min-h-11 items-center gap-0.5 text-[14px] font-semibold text-[var(--accent)] rounded-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
        {more > 0 ? `${more} more reason${more > 1 ? 's' : ''}` : 'Key numbers'}{changes > 0 ? ` · changed ${changes} time${changes > 1 ? 's' : ''}` : ''}
        <ChevronRight className="w-4 h-4" aria-hidden="true" />
      </button>
    </section>
  );
};

export default VerdictSummary;
