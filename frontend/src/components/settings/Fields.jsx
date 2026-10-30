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

// zeroIsOff: a saved 0 (a number, not one being typed) reads as "Off". `prefix` (₹) and `suffix` (%, min) sit inside the box.
export const NumberField = ({ value, onChange, onCommit, zeroIsOff = false, prefix, suffix, label }) => (
  <label className="inline-flex items-center gap-1 w-32 min-h-11 px-3 rounded-[12px] border border-[var(--border)] bg-[var(--surface-2)] focus-within:border-[var(--accent)]">
    {prefix && <span className="text-[15px] text-[var(--text-muted)]">{prefix}</span>}
    <input
      type="number"
      inputMode="numeric"
      aria-label={label}
      value={zeroIsOff && value === 0 ? '' : value}
      placeholder={zeroIsOff ? 'Off' : undefined}
      onChange={(event) => onChange(event.target.value)}
      onBlur={onCommit}
      className="min-w-0 flex-1 bg-transparent text-right figure-md text-[15px] font-semibold tabular-nums text-[var(--text)] placeholder:text-[var(--text-muted)] placeholder:font-normal focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
    />
    {suffix && <span className="text-[13px] text-[var(--text-muted)]">{suffix}</span>}
  </label>
);

const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]';

/** An on/off switch. `danger` paints on as a loss (real money); `disabled` shows a state held by something else. */
export const Toggle = ({ on, onClick, label, danger = false, disabled = false }) => (
  <button type="button" role="switch" aria-checked={Boolean(on)} aria-label={label} onClick={onClick} disabled={disabled}
          className={cn('group inline-flex items-center min-h-11 rounded-full disabled:opacity-50', FOCUS)}>
    <span className={cn('relative h-8 w-[52px] rounded-full border transition-colors duration-150',
      on ? (danger ? 'bg-[var(--loss)] border-[var(--loss)]' : 'bg-[var(--accent)] border-[var(--accent)]') : 'bg-[var(--surface-2)] border-[var(--border)]')}>
      <span className={cn('absolute top-[3px] h-6 w-6 rounded-full transition-[left] duration-150 ease-out',
        on ? 'left-[23px] bg-[var(--accent-ink)]' : 'left-[3px] bg-[var(--text-muted)]')} />
    </span>
  </button>
);

/** One choice out of a few, on a segmented track. `options: [[value, label]]`; `dangerValue` reads red when chosen. */
export const Segmented = ({ options, value, onChange, label, dangerValue, disabled = () => false }) => (
  <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
    {options.map(([v, text]) => (
      <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)} disabled={disabled(v)}
              className={cn('min-h-11 px-4 rounded-[8px] text-[14px] font-medium transition-colors disabled:opacity-40', FOCUS,
                value === v ? (v === dangerValue ? 'bg-[var(--loss)] text-[var(--accent-ink)]' : 'bg-[var(--surface)] text-[var(--text)]') : 'text-[var(--text-muted)]')}>
        {text}
      </button>
    ))}
  </div>
);
