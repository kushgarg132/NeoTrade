import React from 'react';
import { Link } from 'react-router-dom';
import Badge from '../ui/Badge';
import { cn } from '../../utils/cn';
import { impactWord } from '../../utils/market';
import { newsPath } from '../../utils/routes';

/** One scored impact as the News tab shows it: "SUZLON ↓ High" (direction -1..1, impact 0..10). */
export const Impact = ({ impact }) => {
  const arrow = impact.direction > 0 ? '↑' : impact.direction < 0 ? '↓' : '·';
  const cls = impact.direction > 0 ? 'text-[var(--gain)]' : impact.direction < 0 ? 'text-[var(--loss)]' : 'text-[var(--text-muted)]';
  return <span className={`text-[13px] tabular-nums whitespace-nowrap ${cls}`}>{impact.type === 'market' ? 'Market' : impact.target} {arrow} {impactWord(impact.impact)}</span>;
};

/** A story's AI analysis in one line, as on the News tab: the Material badge and its strongest impacts
 * (`impacts` from `backend/datalayer/news.py::ref`). Nothing without either. */
export const ImpactChips = ({ impacts, material = false, max = 3, className }) => {
  const top = [...(impacts || [])].sort((a, b) => (b.impact ?? 0) - (a.impact ?? 0)).slice(0, max);
  if (!top.length && !material) return null;
  return (
    <span className={cn('flex flex-wrap items-center gap-x-3 gap-y-0.5', className)}>
      {material && <Badge kind="alert">Material</Badge>}
      {top.map((i) => <Impact key={`${i.type}-${i.target}`} impact={i} />)}
    </span>
  );
};

/** Where a headline leads: the story's analysis page (/news/:id) when it is stored, else the article. */
export const NewsLink = ({ id, url, className, children, onClick }) => {
  if (id) return <Link to={newsPath(id)} className={className} onClick={onClick}>{children}</Link>;
  if (url) return <a href={url} target="_blank" rel="noopener noreferrer" className={className} onClick={onClick}>{children}</a>;
  return <span className={className}>{children}</span>;
};
