import React from 'react';
import { ImpactChips, NewsLink } from '../common/NewsImpacts';
import { formatDateTime } from '../../utils/formatters';
import { sourceName } from '../../utils/newsItem';

const day = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const LEAN = { 1: ['▲', 'Good news', 'text-[var(--gain)]'], '-1': ['▼', 'Bad news', 'text-[var(--loss)]'], 0: ['◆', 'Mixed', 'text-[var(--text-muted)]'] };

/** The headlines behind one news dot on the price chart, as a swipeable row of compact cards. */
const NewsStrip = ({ mark, onClose }) => (
  <section aria-label={`News on ${day(mark.date)}`} className="mt-3">
    <div className="flex items-center justify-between">
      <h3 className="text-[13px] font-medium text-[var(--text-muted)]">
        News on {day(mark.date)} <span className="tabular-nums">· {mark.items.length}</span>
      </h3>
      <button type="button" onClick={onClose} className="min-h-11 px-2 text-[13px] font-medium text-[var(--accent)]">
        Close
      </button>
    </div>
    <ul className="flex gap-2 overflow-x-auto snap-x snap-mandatory pb-1">
      {mark.items.map((i) => {
        const [glyph, lean, tone] = LEAN[Math.sign(i.direction || 0)];
        return (
          <li key={i.id ?? i.url ?? i.title} className="snap-start shrink-0 w-[min(280px,82vw)] rounded-[12px] bg-[var(--surface-2)] p-3 flex flex-col gap-1.5">
            <span className={`text-[12px] font-medium ${tone}`}>
              <span aria-hidden="true">{glyph}</span> {lean} <span className="text-[var(--text-muted)] tabular-nums">· impact {i.impact}/10</span>
            </span>
            {i.id || i.url ? (
              <NewsLink id={i.id} url={i.url} className="text-[14px] leading-snug line-clamp-3 text-[var(--text)] hover:underline underline-offset-2">{i.title}</NewsLink>
            ) : <span className="text-[14px] leading-snug line-clamp-3">{i.title}</span>}
            <span className="mt-auto text-[12px] text-[var(--text-muted)]">
              {[sourceName(i.source), formatDateTime(i.published_at)].filter(Boolean).join(' · ')}
            </span>
            <ImpactChips impacts={i.impacts} />
          </li>
        );
      })}
    </ul>
  </section>
);

export default NewsStrip;
