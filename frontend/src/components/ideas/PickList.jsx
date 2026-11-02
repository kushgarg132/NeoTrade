import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import GradeTile from '../ui/GradeTile';
import { px } from './levels';
import { GRADES, pickStatus, rankPicks } from '../../utils/ideas';
import { bareSymbol } from '../../utils/formatters';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';

// Status colour by pickStatus kind: a dot and the words, no pill (one quiet line per row).
const STATUS = {
  alert: 'text-[var(--loss)]', unproven: 'text-[var(--warn)]', neutral: 'text-[var(--text-muted)]', proven: 'text-[var(--gain)]',
};
// One template for the header and the rows: rank, stock, status (sm+), expected, how sure, chevron.
const COLS = 'grid grid-cols-[20px_minmax(0,1fr)_auto_auto_14px] sm:grid-cols-[24px_minmax(0,1fr)_170px_92px_84px_14px] items-center gap-x-3';

const Status = ({ s, className = '' }) => s && (
  <span className={`inline-flex items-center gap-1.5 text-[13px] font-medium ${STATUS[s.kind]} ${className}`}>
    <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />{s.label}
  </span>
);

/** How sure, in the list's one unit: a pick's chance up, else the engine's composite score. */
const sureText = (idea) => (idea.kind === 'p'
  ? (typeof idea.pUp === 'number' ? `${Math.round(idea.pUp * 100)}% up` : '–')
  : (idea.score?.final != null ? `${Math.round(idea.score.final * 100)}/100` : '–'));

/** One idea on one row: rank, grade and symbol over setup · days · entry, its status, the expected move and how sure.
 *  The whole row opens the idea's page, where the levels, the range and Skip / Buy live. */
const Row = ({ idea, rank, news, results }) => {
  const key = bareSymbol(idea.symbol)?.toUpperCase();
  const status = pickStatus(idea, { news: news?.[key], results: results?.[key] });
  const move = idea.headline?.value;
  const entry = idea.entry != null ? `entry ${px(idea.entry)}` : null;
  const sub = [idea.setup, idea.horizon && `${idea.horizon}d`].filter(Boolean).join(' · ');
  return (
    <li>
      <Link to={`/ideas/${encodeURIComponent(idea.id)}`}
        className={`tap ${COLS} -mx-2 rounded-[12px] px-2 py-3 hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`}>
        <span className="text-[13px] font-semibold tabular-nums text-[var(--text-muted)]">{rank}</span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {GRADES[idea.grade] && <GradeTile grade={idea.grade} small />}
            {idea.side !== 'BUY' && <span className="text-[12px] font-semibold text-[var(--loss)]">{idea.side}</span>}
            <span className="truncate text-[16px] font-bold tracking-[-0.01em] text-[var(--text)]">{bareSymbol(idea.symbol)}</span>
          </div>
          <div className="mt-0.5 truncate text-[13px] text-[var(--text-muted)] tabular-nums">{sub}<span className="hidden sm:inline">{entry && ` · ${entry}`}</span></div>
          {/* Phones: the status and the entry share a line under the setup; sm+ gives the status its own column. */}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[13px] tabular-nums sm:hidden">
            <Status s={status} />{entry && <span className="text-[var(--text-muted)]">{entry}</span>}
          </div>
        </div>
        <span className="hidden sm:block"><Status s={status} /></span>
        <div className="text-right tabular-nums">
          <div className={`text-[17px] font-bold leading-tight ${move != null ? toneText(tone(move)) : 'text-[var(--text-muted)]'}`}>{move != null ? pct(move, { sign: true, dp: 1 }) : '–'}</div>
          <div className="text-[12px] text-[var(--text-muted)] whitespace-nowrap">{idea.kind === 'p' ? 'expected' : idea.headline?.label || ''}</div>
        </div>
        <div className="text-right text-[14px] font-semibold tabular-nums text-[var(--text)] whitespace-nowrap">{sureText(idea)}</div>
        <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" aria-hidden="true" />
      </Link>
    </li>
  );
};

const Head = ({ sure = 'Chance up' }) => (
  <div className={`hidden sm:grid ${COLS.replace('grid ', '')} px-0 pb-1 text-[12px] text-[var(--text-muted)]`} aria-hidden="true">
    <span>#</span><span>Stock</span><span>Status</span><span className="text-right">Expected</span><span className="text-right">{sure}</span><span />
  </div>
);

const Section = ({ title, note, children }) => (
  <section className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4 pt-4 pb-2">
    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
      <h2 className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">{title}</h2>
      {note}
    </div>
    {children}
  </section>
);

/** Picks tab: one list ranked best first (utils/ideas.js::rankPicks). Engine ideas (admins) above it; grade C folded
 *  at the end. A row is one line of facts and one status; everything else is on the idea's page. */
const PickList = ({ items, news, results, showUnproven, onToggleUnproven, hiddenCount, hiddenReason }) => {
  const { engine, ranked, unproven } = rankPicks(items);
  const rows = (list, from = 1) => list.map((idea, i) => <Row key={idea.id} idea={idea} rank={from + i} news={news} results={results} />);
  return (
    <div className="space-y-4">
      {engine.length > 0 && (
        <Section title="Engine ideas" note={<span className="text-[13px] text-[var(--text-muted)]">by score</span>}>
          <Head sure="Score" />
          <ul className="divide-y divide-[var(--border)]">{rows(engine)}</ul>
        </Section>
      )}
      {(ranked.length > 0 || unproven.length > 0) && (
        <Section title="Picks · best first" note={<span className="text-[13px] text-[var(--text-muted)]">A proven · B promising</span>}>
          <p className="mt-1 mb-2 text-[13px] leading-snug text-[var(--text-muted)]">
            Each pick: buy near the entry, hold to the due date. The stop is only protection. Paper record · not advice.
          </p>
          {ranked.length === 0 && <p className="py-2 text-[14px] text-[var(--text-muted)]">No proven setup has fired right now. The ones below have no edge over the average stock so far.</p>}
          {ranked.length > 0 && <><Head /><ul className="divide-y divide-[var(--border)]">{rows(ranked)}</ul></>}
          {unproven.length > 0 && (
            <div className="border-t border-[var(--border)]">
              <button type="button" aria-expanded={showUnproven} onClick={onToggleUnproven}
                className="min-h-11 w-full text-left text-[14px] font-semibold text-[var(--text-muted)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[8px]">
                {showUnproven ? 'Hide' : 'Show'} {unproven.length} unproven pick{unproven.length > 1 ? 's' : ''} (C: no edge yet)
              </button>
              {showUnproven && <ul className="divide-y divide-[var(--border)] opacity-80">{rows(unproven, ranked.length + 1)}</ul>}
            </div>
          )}
          {hiddenCount > 0 && <p className="pb-2 text-[13px] text-[var(--text-muted)]" title={hiddenReason}>{hiddenCount} more kept back (top 3 per grade).</p>}
        </Section>
      )}
    </div>
  );
};

export default PickList;
