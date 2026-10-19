/** Helpers for the stock page. Pure. */

/** Header numbers for a held position; null when not held (or sold). `portfolioValue` gives the weight. */
export const positionSummary = (position, portfolioValue) => {
  if (!position || position.sold || !(position.qty > 0)) return null;
  const { qty, avg_price: avg, value, pnl, pnl_pct: pnlPct } = position;
  return {
    qty,
    avg,
    value,
    pnl,
    pnlPct: pnlPct == null ? null : pnlPct / 100, // the API sends percent, the ui/format helpers take a fraction
    weight: value != null && portfolioValue > 0 ? value / portfolioValue : null,
  };
};

/**
 * Where the owner's trades sit on a price series. A trade on a day with no close (holiday, import gap)
 * snaps to the last close on or before it; one before the series starts is dropped.
 * `closes`: [{date: 'YYYY-MM-DD', close}], `trades`: [{date, side, price?}].
 */
export const tradeMarkers = (closes, trades) =>
  (trades || [])
    .map((t) => {
      let at = null;
      for (const c of closes || []) if (c.date <= t.date) at = c;
      return at && { date: at.date, side: t.side, price: t.price ?? at.close };
    })
    .filter(Boolean);
