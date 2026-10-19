import React from 'react';

/** A titled surface. `action` sits at the right of the title row. */
const Card = ({ title, action, children, className = '' }) => (
  <section className={`rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-4 ${className}`}>
    {(title || action) && (
      <div className="flex items-center justify-between gap-3 mb-3 min-h-6">
        {title && <h2 className="text-[15px] font-semibold text-[var(--text)]">{title}</h2>}
        {action}
      </div>
    )}
    {children}
  </section>
);

export default Card;
