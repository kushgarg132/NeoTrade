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
    return <div className="text-[13px] text-[var(--text-muted)] mt-0.5">{text}</div>;
  }
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        setOpen((value) => !value);
      }}
      aria-expanded={open}
      className="text-[13px] text-[var(--text-muted)] mt-0.5 text-left w-full"
    >
      <span className={cn('block', !open && 'line-clamp-2')}>{text}</span>
      <span className="underline">{open ? 'Less' : 'More'}</span>
    </button>
  );
};

export const Row = ({ label, hint, children }) => (
  <div className="py-2 border-b border-[var(--border)] last:border-b-0">
    {/* A control too wide to leave the label 10rem wraps under it. */}
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <div className="min-w-[10rem] flex-1">
        <p className="text-[13px] font-medium text-[var(--text-muted)]">{label}</p>
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
    className="w-24 bg-[var(--surface)] border border-[var(--border)] rounded-[12px] px-2 min-h-11 text-right figure-md text-[15px] tabular-nums placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
  />
);

const PILL = 'min-h-11 px-3 rounded-full border text-[14px] font-semibold transition-colors';
const PILL_ON = 'bg-[var(--text)] text-[var(--surface)] border-[var(--text)]';
const PILL_ON_DANGER = 'bg-[var(--loss)] text-[var(--surface)] border-[var(--loss)]';
const PILL_OFF = 'text-[var(--text-muted)] border-[var(--border)] bg-[var(--surface)]';

/** An on/off switch as a pill. */
export const Toggle = ({ on, onClick, label, onText = 'On', offText = 'Off', danger = false }) => (
  <button type="button" role="switch" aria-checked={Boolean(on)} aria-label={label} onClick={onClick}
          className={cn(PILL, on ? (danger ? PILL_ON_DANGER : PILL_ON) : PILL_OFF)}>
    {on ? onText : offText}
  </button>
);

/** One choice out of a few, as joined pills. `options: [[value, label]]`; `dangerValue` reads red when chosen. */
export const Segmented = ({ options, value, onChange, label, dangerValue }) => (
  <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
    {options.map(([v, text]) => (
      <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)}
              className={cn(PILL, value === v ? (v === dangerValue ? PILL_ON_DANGER : PILL_ON) : PILL_OFF)}>
        {text}
      </button>
    ))}
  </div>
);
