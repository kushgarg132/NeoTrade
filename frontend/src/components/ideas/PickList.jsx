import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight } from 'lucide-react';
import GradeTile from '../ui/GradeTile';
import { GRADES, pickStatus, rankPicks } from '../../utils/ideas';
import { bareSymbol } from '../../utils/formatters';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import StockIcon from '../ui/StockIcon';

// Status colour by pickStatus kind: a dot and the words, no pill.
const STATUS = {
  alert: 'text-[var(--loss)]', unproven: 'text-[var(--warn)]', neutral: 'text-[var(--text-muted)]', proven: 'text-[var(--gain)]',
};
const ring = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]';

/** How sure, in the list's one unit: a pick's chance up, else the engine's composite score. */
const sureText = (idea) => (idea.kind === 'p'
  ? (typeof idea.pUp === 'number' ? `${Math.round(idea.pUp * 100)}% up` : null)
  : (idea.score?.final != null ? `${Math.round(idea.score.final * 100)}/100` : null));

/** "27d" (days left) for a pick past its first day, else its hold ("40d hold"). */
const timeText = (idea) => (idea.kind === 'p' && idea.daysSince > 0 && idea.daysLeft != null ? `${idea.daysLeft}d`
  : idea.horizon ? `${idea.horizon}d hold` : null);

/**
 * One idea, two lines, the same grammar as Market's and AI's lists. Line one: logo, symbol, grade, and the expected
 * move. Line two: the status (a dot and its word) and the setup, then how sure and the time left. The row opens the
 * idea's page, where the levels and Skip / Buy live.
 */
const Row = ({ idea, news, results }) => {
  const key = bareSymbol(idea.symbol)?.toUpperCase();
  const status = pickStatus(idea, { news: news?.[key], results: results?.[key] });
  const move = idea.headline?.value;
  const broken = status?.label === 'Below stop'; // the forecast no longer describes this trade: no gain tone
  const sure = sureText(idea);
  const time = timeText(idea);
  return (
    <li className="border-b border-[var(--border)] last:border-b-0">
      <Link to={`/ideas/${encodeURIComponent(idea.id)}`}
        className={`tap flex items-center gap-3 -mx-2 px-2 py-3 rounded-[12px] hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] ${ring}`}>
        <StockIcon symbol={idea.symbol} className="size-8" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="min-w-0 truncate text-[15px] font-bold text-[var(--text)]">{bareSymbol(idea.symbol)}</span>
            {GRADES[idea.grade] && <GradeTile grade={idea.grade} small />}
            {idea.side !== 'BUY' && <span className="text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--loss)]">{idea.side}</span>}
            <span className={`ml-auto shrink-0 text-[15px] font-bold tabular-nums ${move != null && !broken ? toneText(tone(move)) : 'text-[var(--text-muted)]'}`}>
              {move != null ? pct(move, { sign: true, dp: 1 }) : '–'}
            </span>
          </div>
          <div className="mt-0.5 flex items-start gap-2 text-[13px] leading-snug">
            <span className="min-w-0 flex-1 line-clamp-2 text-[var(--text-muted)]">
              {status && (
                <span className={`font-medium ${STATUS[status.kind]}`}>
                  <span aria-hidden="true" className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current align-middle" />{status.label}
                  <span className="text-[var(--text-muted)] font-normal"> · </span>
                </span>
              )}
              {idea.setup}
            </span>
            {(sure || time) && (
              <span className="shrink-0 tabular-nums text-[var(--text-muted)]">
                {[sure, time].filter(Boolean).join(' · ')}
              </span>
            )}
          </div>
        </div>
        <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
      </Link>
    </li>
  );
};

/**
 * Ideas' second lane, "New picks": one list best first (`utils/ideas.js::rankPicks`): engine ideas, then grades A and
 * B, then C (no edge yet) folded behind a toggle. A row is two lines of facts and one status; everything else is on
 * the idea's page.
 */
const PickList = ({ items, news, results, showUnproven, onToggleUnproven, hiddenCount, hiddenReason }) => {
  const { engine, ranked, unproven } = rankPicks(items);
  const rows = (list) => list.map((idea) => <Row key={idea.id} idea={idea} news={news} results={results} />);
  return (
    <>
      {engine.length + ranked.length > 0
        ? <ul>{rows(engine)}{rows(ranked)}</ul>
        : <p className="py-4 text-[14px] text-[var(--text-muted)]">No proven setup has fired right now. The ones below have no edge over the average stock so far.</p>}
      {unproven.length > 0 && (
        <div className="border-t border-[var(--border)]">
          <button type="button" aria-expanded={showUnproven} onClick={onToggleUnproven}
            className={`tap flex w-full items-center gap-3 min-h-12 text-left text-[14px] text-[var(--text-muted)] hover:text-[var(--text)] rounded-[12px] ${ring}`}>
            <span className="flex-1">{unproven.length} unproven pick{unproven.length > 1 ? 's' : ''} (C: no edge yet)</span>
            <ChevronDown className={`w-4 h-4 shrink-0 transition-transform ${showUnproven ? 'rotate-180' : ''}`} aria-hidden="true" />
          </button>
          {showUnproven && <ul className="fade-in border-t border-[var(--border)]">{rows(unproven)}</ul>}
        </div>
      )}
      <p className="border-t border-[var(--border)] py-3 text-[12px] leading-snug text-[var(--text-muted)]" title={hiddenReason || undefined}>
        Buy near the entry, hold to the due date; the stop is only protection.
        {hiddenCount > 0 && ` ${hiddenCount} more kept back (top 3 per grade).`}
      </p>
    </>
  );
};

export default PickList;
