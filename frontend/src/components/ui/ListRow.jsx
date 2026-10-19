import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { toneText } from './tone';

/** One list line: title + sub-line on the left, a value on the right. `to` links, `onClick` acts. */
const ListRow = ({ title, sub, right, rightTone = 'neutral', to, onClick, chevron = true }) => {
  const body = (
    <>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-medium text-[var(--text)] truncate">{title}</div>
        {sub && <div className="text-[13px] text-[var(--text-muted)] truncate">{sub}</div>}
      </div>
      {right != null && <div className={`private figure-md shrink-0 text-[15px] tabular-nums ${toneText(rightTone)}`}>{right}</div>}
      {chevron && (to || onClick) && <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />}
    </>
  );
  const cls = 'flex w-full items-center gap-3 min-h-14 py-2 text-left border-b border-[var(--border)] last:border-b-0';
  if (to) return <Link to={to} className={cls}>{body}</Link>;
  if (onClick) return <button type="button" onClick={onClick} className={cls}>{body}</button>;
  return <div className={cls}>{body}</div>;
};

export default ListRow;
