import React, { useState } from 'react';
import { cn } from '../../utils/cn';

/**
 * The settings form's two field shapes, shared by Settings and the Paper
 * tab's engine settings so both read as the same form.
 */

// A hint longer than this is folded to two lines; a tap shows all of it.
const HINT_FOLD = 90;

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
      className="doc-meta normal-case mt-0.5 text-left w-full"
    >
      <span className={cn('block', !open && 'line-clamp-2')}>{text}</span>
      <span className="underline">{open ? 'Less' : 'More'}</span>
    </button>
  );
};

export const Row = ({ label, hint, children }) => (
  <div className="py-2 border-b border-[var(--rule)] last:border-b-0">
    {/* A control too wide to leave the label 10rem wraps under it. */}
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <div className="min-w-[10rem] flex-1">
        <p className="field-label">{label}</p>
        {hint && <Hint text={hint} />}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  </div>
);

// zeroIsOff: a saved 0 (a number, not one being typed) reads as "Off".
export const NumberField = ({ value, onChange, onCommit, zeroIsOff = false }) => (
  <input
    type="number"
    inputMode="numeric"
    value={zeroIsOff && value === 0 ? '' : value}
    placeholder={zeroIsOff ? 'Off' : undefined}
    onChange={(event) => onChange(event.target.value)}
    onBlur={onCommit}
    className="w-24 bg-transparent border-b border-[var(--rule-strong)] py-1 text-right figure-md text-sm placeholder:text-[var(--ink-soft)] focus:outline-none focus:border-[var(--stamp)]"
  />
);
