import React from 'react';

/** One pressable filter chip: accent fill when on. */
export const Chip = ({ on, onClick, children }) => (
  <button type="button" aria-pressed={on} onClick={onClick}
          className={`shrink-0 min-h-11 px-3.5 rounded-full text-[14px] font-medium border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] active:opacity-70 ${on ? 'bg-[var(--accent)] text-[var(--accent-ink)] border-[var(--accent)]' : 'bg-[var(--surface)] text-[var(--text)] border-[var(--border)]'}`}>
    {children}
  </button>
);

/** A side-scrolling row of single-choice chips (`options` [{ id, label }]); `children` adds extra chips at the end. */
const ChipRow = ({ label, options, value, onChange, children, className = '' }) => (
  <div role="group" aria-label={label} className={`-mx-1 flex gap-2 overflow-x-auto px-1 pt-1 ${className}`}>
    {options.map((o) => <Chip key={o.id} on={value === o.id} onClick={() => onChange(o.id)}>{o.label}</Chip>)}
    {children}
  </div>
);

export default ChipRow;
