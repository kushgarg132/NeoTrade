import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

/**
 * A titled surface. `action` sits at the right of the title row.
 * `to` makes the whole card one link; a card that holds links takes `more` ({ to, label }) instead, never both.
 */
const Card = ({ title, action, to, more, children, className = '' }) => {
  const cls = `rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-4 ${className}`;
  const right = to ? <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" /> : action;
  const head = (title || right || more) && (
    <div className="flex items-center justify-between gap-3 mb-3 min-h-6">
      {title && <h2 className="text-[15px] font-semibold text-[var(--text)]">{title}</h2>}
      {right}
      {more && (
        <Link to={more.to} className="inline-flex items-center min-h-11 -my-2.5 text-[13px] font-medium text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
          {more.label ?? 'See all'} ›
        </Link>
      )}
    </div>
  );
  if (to) {
    return (
      <Link to={to} className={`block ${cls} transition-transform hover:bg-[var(--surface-2)] active:scale-[0.98] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`}>
        {head}
        {children}
      </Link>
    );
  }
  return <section className={cls}>{head}{children}</section>;
};

export default Card;
