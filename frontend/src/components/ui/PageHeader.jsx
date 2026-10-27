import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';

/** Page title row. `back` is a path (link) or `true` (history back); `backLabel` names the parent beside the chevron. */
const PageHeader = ({ title, back, backLabel, right }) => {
  const navigate = useNavigate();
  const backCls = 'inline-flex items-center justify-center min-h-11 min-w-11 -ml-2 text-[var(--text-muted)]';
  const aria = backLabel ? `Back to ${backLabel}` : 'Back';
  const inner = <><ChevronLeft className="w-5 h-5" />{backLabel && <span className="text-[13px] pr-1">{backLabel}</span>}</>;
  return (
    <div className="flex items-center gap-2 min-h-11 mb-3">
      {back && (typeof back === 'string' ? (
        <Link to={back} aria-label={aria} className={backCls}>{inner}</Link>
      ) : (
        <button type="button" onClick={() => navigate(-1)} aria-label={aria} className={backCls}>{inner}</button>
      ))}
      <h1 className="flex-1 min-w-0 truncate text-[22px] leading-7 font-bold text-[var(--text)]">{title}</h1>
      {right}
    </div>
  );
};

export default PageHeader;
