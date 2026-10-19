import React from 'react';

/** One-line section error with a Retry. */
const ErrorLine = ({ message = 'Could not load this.', onRetry }) => (
  <div role="alert" className="flex items-center justify-between gap-3 min-h-11 text-[14px] text-[var(--loss)]">
    <span>{message}</span>
    {onRetry && (
      <button type="button" onClick={onRetry} className="min-h-11 px-3 font-semibold text-[var(--accent)]">Retry</button>
    )}
  </div>
);

export default ErrorLine;
