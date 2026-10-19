import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import IdeaBadge from './IdeaBadge';
import { bareSymbol } from '../../utils/formatters';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';

/** One idea in the list: action + symbol, setup and horizon, headline %, proven badge. */
const IdeaRow = ({ idea }) => (
  <Link to={`/ideas/${encodeURIComponent(idea.id)}`} className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0 active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <span className="text-[12px] font-semibold text-[var(--text-muted)]">{idea.side}</span>
        <span className="text-[15px] font-semibold text-[var(--text)] truncate">{bareSymbol(idea.symbol)}</span>
      </div>
      <div className="flex items-center gap-2 text-[13px] text-[var(--text-muted)]">
        <span className="truncate">{idea.setup}{idea.horizon ? ` · ${idea.horizon}d` : ''}</span>
        <span className="shrink-0"><IdeaBadge badge={idea.badge} /></span>
      </div>
    </div>
    {idea.headline?.value != null && (
      <div className="shrink-0 text-right tabular-nums">
        <div className={`text-[15px] font-semibold ${toneText(tone(idea.headline.value))}`}>{pct(idea.headline.value, { sign: true, dp: 1 })}</div>
        <div className="text-[12px] text-[var(--text-muted)]">{idea.headline.label}{idea.kind === 'p' && idea.pBeat != null ? ` · beats ${pct(idea.pBeat, { dp: 0 })}` : ''}</div>
      </div>
    )}
    <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
  </Link>
);

export default IdeaRow;
