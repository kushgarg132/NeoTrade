import React, { useState } from 'react';
import { cn } from '../../utils/cn';

/**
 * The settings form's two field shapes, shared by Settings and the Paper
 * tab's engine settings so both read as the same form.
 */

// A hint longer than this is folded to one line; a tap shows all of it.
const HINT_FOLD = 60;

const Hint = ({ text }) => {
  const [open, setOpen] = useState(false);
  if (typeof text !== 'string' || text.length <= HINT_FOLD) {
    return <div className="doc-meta normal-case mt-0.5">{text}</div>;
  }
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        setOpen((value) => !value);
      }}
      aria-expanded={open}
      className={cn('doc-meta normal-case mt-0.5 text-left w-full', !open && 'line-clamp-1')}
    >
      {text}
    </button>
  );
};

export const Row = ({ label, hint, children }) => (
  <div className="py-2 border-b border-[var(--rule)] last:border-b-0">
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0 flex-1">
        <p className="field-label">{label}</p>
        {hint && <Hint text={hint} />}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  </div>
);

export const NumberField = ({ value, onChange, onCommit }) => (
  <input
    type="number"
    inputMode="numeric"
    value={value}
    onChange={(event) => onChange(event.target.value)}
    onBlur={onCommit}
    className="w-24 bg-transparent border-b border-[var(--rule-strong)] py-1 text-right figure-md text-sm focus:outline-none focus:border-[var(--stamp)]"
  />
);
