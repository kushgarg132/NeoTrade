import React from 'react';
import { cn } from '../../utils/cn';

const TONE = { up: 'text-up', down: 'text-down', neutral: 'text-[var(--ink)]' };

/** Plain-fact chips over the stock (backend/research/flags.py): facts, never a buy or sell call. */
const StockFlags = ({ flags }) => {
  if (!flags?.length) return null;
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="At a glance">
      {flags.map((flag) => (
        <li
          key={flag.code}
          className={cn(
            'px-2 py-1 border border-[var(--rule-strong)] bg-[var(--paper)] font-[family-name:var(--font-narrow)] text-xs font-semibold',
            TONE[flag.tone] || TONE.neutral
          )}
        >
          {flag.label}
        </li>
      ))}
    </ul>
  );
};

export default StockFlags;
