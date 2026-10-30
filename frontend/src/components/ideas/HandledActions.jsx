import React, { useCallback } from 'react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import { useLoad } from './useLoad';
import api, { endpoints } from '../../utils/api';
import { handledSub, handledTitle } from '../../utils/ideasHistory';

/** Holdings rows you dismissed or snoozed (still hidden), newest first, each with Undo. Nothing hidden: no card. */
const HandledActions = ({ onChanged }) => {
  const { data, reload } = useLoad(useCallback(() => api.get(endpoints.mine.handled).then((r) => r.data.handled), []));
  if (!data?.length) return null;
  const undo = (id) => api.post(endpoints.mine.restore(id)).then(() => { reload(); onChanged(); }).catch(() => {});
  return (
    <Card title="Handled">
      <ul>
        {data.map((h) => (
          <li key={h.action_id} className="flex items-center gap-3 py-2.5 border-b border-[var(--border)] last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="text-[15px] font-medium text-[var(--text)]">{handledTitle(h)}</div>
              <div className="text-[13px] text-[var(--text-muted)]">{handledSub(h)}</div>
            </div>
            <Button variant="secondary" className="shrink-0 px-3 text-[14px]" onClick={() => undo(h.action_id)}>Undo</Button>
          </li>
        ))}
      </ul>
    </Card>
  );
};

export default HandledActions;
