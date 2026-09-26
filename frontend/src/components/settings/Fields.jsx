import React from 'react';

/**
 * The settings form's two field shapes, shared by Settings and the Paper
 * tab's engine settings so both read as the same form.
 */

export const Row = ({ label, hint, children }) => (
  <div className="py-3 border-b border-[var(--rule)] last:border-b-0">
    <div className="flex items-baseline justify-between gap-4 flex-wrap">
      <div className="min-w-0">
        <p className="field-label">{label}</p>
        {hint && <p className="doc-meta normal-case mt-1">{hint}</p>}
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
    className="w-36 bg-transparent border-b border-[var(--rule-strong)] py-1 text-right figure-md text-sm focus:outline-none focus:border-[var(--stamp)]"
  />
);
