import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import Card from '../ui/Card';
import ListRow from '../ui/ListRow';
import { inr, pct, tone } from '../ui/format';
import { AiLabel, AmountText } from '../ai/AiSummary';
import { bareSymbol } from '../../utils/formatters';
import { newsWhy, todayTitle, briefLines } from '../../utils/home';
import { ImpactChips } from '../common/NewsImpacts';
import { newsPath } from '../../utils/routes';

/**
 * The day's story: the account's big news moves (pulse.news_moves, backend/portfolio/news_moves.py; a tap opens
 * the story's analysis, else the headline) and the brief (the AI's three lines when a job wrote them, else the digest's first lines with
 * "Read all"). Renders nothing when neither has content.
 */
const TodayCard = ({ moves, kind, text, summary }) => {
  const [all, setAll] = useState(false);
  const { ai, lines } = briefLines(text, summary);
  const hasMoves = Boolean(moves?.length);
  if (!hasMoves && !lines.length) return null;
  const shown = all || ai ? lines : lines.slice(0, 3);
  return (
    <Card title={todayTitle(kind)} more={kind === 'premarket' ? { to: '/market', label: 'Market' } : { to: '/money', label: 'Your money' }}>
      {hasMoves && (
        <ul>
          {moves.map((m) => (
            <li key={m.symbol}>
              <ListRow dense title={`${bareSymbol(m.symbol)} ${pct(m.move_pct / 100, { sign: true, dp: 1 })}`}
                sub={newsWhy(m)} extra={m.cause && <ImpactChips impacts={m.cause.impacts} />} right={inr(m.rupees, { sign: true })} rightTone={tone(m.rupees)}
                to={m.cause?.id ? newsPath(m.cause.id) : undefined}
                onClick={!m.cause?.id && m.cause?.url ? () => window.open(m.cause.url, '_blank', 'noopener,noreferrer') : undefined} />
            </li>
          ))}
        </ul>
      )}
      {lines.length > 0 && (
        <div className={hasMoves ? 'border-t border-[var(--border)] pt-3 mt-3' : ''}>
          {ai && <div className="mb-2"><AiLabel at={summary.at} /></div>}
          <ul className="space-y-1.5 text-[15px] text-[var(--text)]">
            {shown.map((line, i) => <li key={i}>{ai ? <AmountText text={line} /> : line}</li>)}
          </ul>
          {!ai && lines.length > 3 && (
            <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all}
                    className="mt-1 inline-flex items-center gap-1 min-h-11 text-[14px] font-semibold text-[var(--accent)] active:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
              {all ? 'Show less' : 'Read all'}
              <ChevronDown className={`w-4 h-4 transition-transform ${all ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>
          )}
        </div>
      )}
    </Card>
  );
};

export default TodayCard;
