import React, { useCallback, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import Button from '../ui/Button';
import { useLoad } from './useLoad';
import api, { endpoints } from '../../utils/api';
import { handledSub, handledTitle } from '../../utils/ideasHistory';

/** Holdings rows you dismissed or snoozed (still hidden), newest first, each with Undo; folded under one line
 * by default. Nothing hidden: nothing shown. */
const HandledActions = ({ onChanged }) => {
  const [open, setOpen] = useState(false);
  const { data, reload } = useLoad(useCallback(() => api.get(endpoints.mine.handled).then((r) => r.data.handled), []));
  if (!data?.length) return null;
  const undo = (id) => api.post(endpoints.mine.restore(id)).then(() => { reload(); onChanged(); }).catch(() => {});
  return (
    <section>
      <button type="button" aria-expanded={open} aria-controls="handled-list" onClick={() => setOpen((v) => !v)}
        className="tap flex w-full items-center gap-2 min-h-11 text-left text-[14px] font-semibold text-[var(--text-muted)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[12px]">
        Handled <span className="font-medium tabular-nums">{data.length}</span>
        <ChevronDown className={`w-4 h-4 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && (
        <ul id="handled-list" className="fade-in mt-1 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4">
          {data.map((h) => (
            <li key={h.action_id} className="flex items-center gap-3 py-2.5 border-b border-[var(--border)] last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="text-[15px] font-medium text-[var(--text)] truncate">{handledTitle(h)}</div>
                <div className="text-[13px] text-[var(--text-muted)]">{handledSub(h)}</div>
              </div>
              <Button variant="secondary" className="shrink-0 px-3 text-[14px]" onClick={() => undo(h.action_id)}>Undo</Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

export default HandledActions;
