import React from 'react';
import { cn } from '../../utils/cn';
import { chipLabel, tone } from '../../utils/news';

const TONE = { pos: 'text-up', neg: 'text-down', flat: 'text-[var(--ink-soft)]' };

/** The news layer's read on one stock: signed sentiment and its latest headline. */
const NewsChip = ({ entry, className }) => {
  if (!entry) return null;
  return (
    <span className={cn('block doc-meta normal-case truncate max-w-[18rem]', className)}
          title={entry.headline || undefined}>
      <span className={cn('field-label mr-1', TONE[tone(entry)] || TONE.flat)}>{chipLabel(entry)}</span>
      {entry.headline && (entry.url ? (
        <a href={entry.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
           className="hover:underline">{entry.headline}</a>
      ) : entry.headline)}
    </span>
  );
};

export default NewsChip;
