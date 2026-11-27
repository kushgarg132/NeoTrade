import React from 'react';

/**
 * A holding's one trade as a stamp: side over quantity, tinted by side (`--loss-soft` sell, `--gain-soft` buy). It opens
 * the order ticket, which is the review; solid red waits for the ticket's final confirm. Today's Needs you and Ideas'
 * holdings lane share it so the same decision looks the same everywhere.
 */
const Stamp = ({ side, quantity, onClick }) => {
  const sell = side === 'Sell';
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${side} ${quantity} shares, opens the order ticket`}
      className={`tap shrink-0 w-14 h-12 rounded-[12px] grid place-content-center justify-items-center gap-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
        sell ? 'bg-[var(--loss-soft)] text-[var(--loss)]' : 'bg-[var(--gain-soft)] text-[var(--gain)]'
      }`}
    >
      <span className="text-[12px] font-extrabold tracking-[0.06em] uppercase leading-none">{side}</span>
      <span className="text-[17px] font-extrabold leading-none tabular-nums">{quantity}</span>
    </button>
  );
};

export default Stamp;
