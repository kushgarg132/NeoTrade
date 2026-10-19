import React from 'react';

/** Loading placeholder: `rows` grey bars. */
const Skeleton = ({ rows = 3 }) => (
  <div role="status" aria-label="Loading" className="space-y-3 animate-pulse">
    {Array.from({ length: rows }, (_, i) => (
      <div key={i} className="h-5 rounded-[8px] bg-[var(--surface-2)]" style={{ width: `${100 - (i % 3) * 12}%` }} />
    ))}
  </div>
);

export default Skeleton;
