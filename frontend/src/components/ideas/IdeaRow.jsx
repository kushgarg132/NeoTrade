import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import IdeaBadge from './IdeaBadge';
import Badge from '../ui/Badge';
import { px, rewardRisk as rr } from './levels';
import { olderPickLabel, GRADES } from '../../utils/ideas';
import { bareSymbol } from '../../utils/formatters';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';

/** One idea in the list: action + symbol, setup and horizon, headline %, proven badge. */
const IdeaRow = ({ idea }) => (
  <Link to={`/ideas/${encodeURIComponent(idea.id)}`} className="flex items-center gap-3 min-h-11 py-1.5 border-b border-[var(--border)] last:border-b-0 active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <span className="text-[12px] font-semibold text-[var(--text-muted)]">{idea.side}</span>
        <span className="text-[15px] font-semibold text-[var(--text)] truncate">{bareSymbol(idea.symbol)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 text-[13px] text-[var(--text-muted)]">
        <span>{idea.setup}{idea.horizon && !olderPickLabel(idea) ? ` · ${idea.horizon}d` : ''}</span>
        <span className="shrink-0"><IdeaBadge badge={idea.badge} /></span>
        {GRADES[idea.grade] && <span className="shrink-0"><Badge kind={GRADES[idea.grade].kind}>{GRADES[idea.grade].label}</Badge></span>}
        {idea.experimental && <span className="shrink-0"><Badge>Experimental</Badge></span>}
      </div>
      {idea.entry != null && (
        <div className="flex flex-wrap gap-x-2 text-[13px] text-[var(--text)] tabular-nums">
          <span className="whitespace-nowrap">Entry {px(idea.entry)}</span>
          {idea.stop != null && <span className="whitespace-nowrap">SL {px(idea.stop)}</span>}
          {idea.target != null && <span className="whitespace-nowrap">T {px(idea.target)}</span>}
          {rr(idea) != null && <span className="whitespace-nowrap font-semibold">R:R {rr(idea).toFixed(1)}</span>}
        </div>
      )}
      {olderPickLabel(idea) && <div className="text-[12px] text-[var(--text-muted)] tabular-nums">{olderPickLabel(idea)}</div>}
      {idea.kind === 'p' && idea.spread && (
        <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
          Range {pct(idea.spread.p10, { sign: true, dp: 1 })} to {pct(idea.spread.p90, { sign: true, dp: 1 })}{idea.pUp != null ? ` · chance up ${pct(idea.pUp, { dp: 0 })}` : ''}
          {idea.exMedian != null && <span className="text-[12px]"> · vs NIFTY {pct(idea.exMedian, { sign: true, dp: 1 })}{idea.pBeat != null ? ` · beats ${pct(idea.pBeat, { dp: 0 })}` : ''}</span>}
        </div>
      )}
    </div>
    {idea.headline?.value != null && (
      <div className="shrink-0 max-w-[88px] text-right tabular-nums">
        <div className={`text-[15px] font-semibold ${toneText(tone(idea.headline.value))}`}>{pct(idea.headline.value, { sign: true, dp: 1 })}</div>
        <div className="text-[12px] text-[var(--text-muted)]">{idea.headline.label}{idea.kind === 'p' && idea.expectedMedian == null && idea.pBeat != null ? ` · beats ${pct(idea.pBeat, { dp: 0 })}` : ''}</div>
      </div>
    )}
    <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
  </Link>
);

export default IdeaRow;
