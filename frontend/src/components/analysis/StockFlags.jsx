import React from 'react';
import { toneText } from '../ui/tone';

const TONE = { up: 'gain', down: 'loss' };

/** Plain-fact chips over the stock (backend/research/flags.py): facts, never a buy or sell call. */
const StockFlags = ({ flags }) => {
  if (!flags?.length) return null;
  return (
    <ul className="flex flex-wrap gap-2" aria-label="At a glance">
      {flags.map((flag) => (
        <li key={flag.code} className={`px-3 min-h-8 inline-flex items-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[13px] font-medium ${toneText(TONE[flag.tone])}`}>
          {flag.label}
        </li>
      ))}
    </ul>
  );
};

export default StockFlags;
