/**
 * Order-ticket props from a suggested trade: a holding row's AI action or a
 * rebalance trade (`{ symbol, suggested: trade }`). Null when there is
 * nothing to trade -- at target, skipped, or no suggestion.
 */
export const ticketFrom = (row) => {
  const s = row?.suggested;
  if (!s?.side) return null;
  return { symbol: row.symbol, side: s.side, quantity: s.quantity, limitPrice: s.price, lastPrice: row.last_price ?? s.price };
};
