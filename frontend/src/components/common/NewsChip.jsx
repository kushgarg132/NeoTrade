import React from 'react';
import { cn } from '../../utils/cn';
import { chipLabel, tone } from '../../utils/news';
import { ImpactChips, NewsLink } from './NewsImpacts';

const TONE = { pos: 'text-up', neg: 'text-down', flat: 'text-[var(--text-muted)]' };

/** The news layer's read on one stock: signed sentiment and its latest headline, then that story's AI analysis
 * as on the News tab (`ImpactChips`). The headline opens the analysis page. `link={false}` inside a button row:
 * a link may not nest in a button. */
const NewsChip = ({ entry, className, link = true }) => {
  if (!entry) return null;
  return (
    <span className={cn('block text-[13px] text-[var(--text-muted)] max-w-[22rem]', className)}>
      <span className="block truncate" title={entry.headline || undefined}>
        <span className={cn('field-label mr-1', TONE[tone(entry)] || TONE.flat)}>{chipLabel(entry)}</span>
        {entry.headline && (link ? (
          <NewsLink id={entry.id} url={entry.url} onClick={(e) => e.stopPropagation()} className="hover:underline">{entry.headline}</NewsLink>
        ) : entry.headline)}
      </span>
      {entry.headline && <ImpactChips impacts={entry.impacts} className="mt-0.5" />}
    </span>
  );
};

export default NewsChip;
