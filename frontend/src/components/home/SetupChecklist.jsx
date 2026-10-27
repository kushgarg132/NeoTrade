import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, Circle, ChevronRight, MinusCircle } from 'lucide-react';
import Card from '../ui/Card';
import api, { endpoints } from '../../utils/api';

/** First-run steps; gone once each is done or skipped. Skipping is saved to the account (`setup_skipped`). */
const SetupChecklist = ({ setup }) => {
  // null until the user skips or undoes here; then it wins over the server's list until the next /today.
  const [skippedHere, setSkippedHere] = useState(null);
  const [error, setError] = useState(false);
  if (!setup) return null;
  const skipped = new Set(skippedHere ?? setup.steps.filter((s) => s.skipped).map((s) => s.id));
  const steps = setup.steps.map((s) => ({ ...s, skipped: !s.done && skipped.has(s.id) }));
  const done = steps.filter((s) => s.done || s.skipped).length;
  if (done === setup.total) return null;

  const save = (id, skip) => {
    const next = [...skipped].filter((x) => x !== id).concat(skip ? [id] : []);
    const before = skippedHere;
    setSkippedHere(next);
    setError(false);
    api.put(endpoints.settings.preferences, { setup_skipped: next }).catch(() => { setSkippedHere(before); setError(true); });
  };

  return (
    <Card title="Set up NeoTrade" action={<span className="text-[13px] text-[var(--text-muted)] tabular-nums">{done}/{setup.total}</span>}>
      {error && <p role="alert" className="mb-1 text-[13px] text-[var(--loss)]">Couldn't save that. Try again.</p>}
      <ul className="divide-y divide-[var(--border)]">
        {steps.map((s) => (
          <li key={s.id} className="flex items-center gap-2">
            <Link to={s.link} className="flex flex-1 min-w-0 items-center gap-3 min-h-11 text-[15px] active:bg-[var(--surface-2)]">
              {s.done ? <Check className="w-4 h-4 shrink-0 text-[var(--gain)]" aria-hidden="true" />
                : s.skipped ? <MinusCircle className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
                : <Circle className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />}
              <span className={s.done || s.skipped ? 'text-[var(--text-muted)] line-through' : 'text-[var(--text)]'}>{s.label}</span>
              {s.skipped && <span className="text-[13px] text-[var(--text-muted)]">Skipped</span>}
              <ChevronRight className="ml-auto w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
            </Link>
            {!s.done && (
              <button type="button" onClick={() => save(s.id, !s.skipped)} aria-label={`${s.skipped ? 'Undo skip' : 'Skip'}: ${s.label}`}
                className="shrink-0 min-h-11 min-w-11 px-2 text-[14px] font-semibold text-[var(--accent)]">
                {s.skipped ? 'Undo' : 'Skip'}
              </button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
};

export default SetupChecklist;
