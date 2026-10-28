import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft } from 'lucide-react';
import { backStep } from '../../utils/routes';

/** Page title row. `back` is the parent path (or `true`): Back goes back in history when there is in-app history,
 * else to that path (utils/routes.js::backStep). `backLabel` names the parent beside the chevron. */
const PageHeader = ({ title, back, backLabel, right }) => {
  const navigate = useNavigate();
  const backCls = 'inline-flex items-center justify-center min-h-11 min-w-11 -ml-2 text-[var(--text-muted)]';
  const aria = backLabel ? `Back to ${backLabel}` : 'Back';
  const inner = <><ChevronLeft className="w-5 h-5" />{backLabel && <span className="text-[13px] pr-1">{backLabel}</span>}</>;
  return (
    <div className="flex items-center gap-2 min-h-11 mb-3">
      {back && (
        <button type="button" aria-label={aria} className={backCls} onClick={() => {
          const step = backStep(window.history.state?.idx ?? 0, back);
          if (step === -1) navigate(-1);
          else navigate(step, { replace: true });
        }}>{inner}</button>
      )}
      <h1 className="flex-1 min-w-0 truncate text-[22px] leading-7 font-bold tracking-[-0.02em] text-[var(--text)]">{title}</h1>
      {right}
    </div>
  );
};

export default PageHeader;
