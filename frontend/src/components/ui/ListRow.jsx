import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { toneText } from './tone';

/** One list line: title + sub-line on the left, a value on the right. `to` links, `onClick` acts.
 *  `dense` is the 36 px trader-list row: more rows per glance, for lists only.
 *  `privateValue={false}` for public figures (market quotes) that hide-amounts must not blur. */
const ListRow = ({ title, sub, right, rightTone = 'neutral', to, onClick, chevron = true, dense = false, privateValue = true }) => {
  const body = (
    <>
      <div className="min-w-0 flex-1">
        <div className={`${dense ? 'text-[14px]' : 'text-[15px]'} font-medium text-[var(--text)] truncate`}>{title}</div>
        {sub && <div className={`${dense ? 'text-[12px]' : 'text-[13px]'} text-[var(--text-muted)] truncate`}>{sub}</div>}
      </div>
      {right != null && <div className={`${privateValue ? 'private ' : ''}figure-md shrink-0 ${dense ? 'text-[14px]' : 'text-[15px]'} tabular-nums ${toneText(rightTone)}`}>{right}</div>}
      {chevron && (to || onClick) && <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />}
    </>
  );
  const tap = to || onClick ? ' hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]' : '';
  const cls = `flex w-full items-center gap-3 ${dense ? 'min-h-9 py-1' : 'min-h-14 py-2'} text-left border-b border-[var(--border)] last:border-b-0${tap}`;
  if (to) return <Link to={to} className={cls}>{body}</Link>;
  if (onClick) return <button type="button" onClick={onClick} className={cls}>{body}</button>;
  return <div className={cls}>{body}</div>;
};

export default ListRow;
