import React from 'react';
import { Link } from 'react-router-dom';
import { Check, Circle } from 'lucide-react';
import Card from '../ui/Card';

/** First-run steps; gone once all are done. */
const SetupChecklist = ({ setup }) => {
  if (!setup || setup.done === setup.total) return null;
  return (
    <Card title="Set up NeoTrade" action={<span className="text-[13px] text-[var(--text-muted)] tabular-nums">{setup.done}/{setup.total}</span>}>
      <ul className="divide-y divide-[var(--border)]">
        {setup.steps.map((s) => (
          <li key={s.id}>
            <Link to={s.link} className="flex items-center gap-3 min-h-11 text-[15px]">
              {s.done
                ? <Check className="w-4 h-4 shrink-0 text-[var(--gain)]" aria-hidden="true" />
                : <Circle className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />}
              <span className={s.done ? 'text-[var(--text-muted)] line-through' : 'text-[var(--text)]'}>{s.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
};

export default SetupChecklist;
