/** Helpers for the Mine pages (Overview, Holdings, Stock, Tax). */

export const RANGES = ['1M', '6M', '1Y', 'ALL'];
export const rangeLabel = (r) => (r === 'ALL' ? 'All' : r);

/** Where a Needs-you row leads: a page, an order ticket, or an idea to decide. */
export const actionTarget = (item) => {
  const a = item?.action || {};
  switch (a.type) {
    case 'stock':
      return { to: `/mine/stock/${encodeURIComponent(item.symbol)}` };
    case 'tax':
      return { to: '/mine/tax' };
    case 'rebalance':
      return { to: '/mine/holdings?plan=1' };
    case 'ticket':
      return { ticket: { symbol: item.symbol, side: a.side, quantity: a.quantity, limitPrice: a.price } };
    case 'idea':
      return { to: '/mine', idea: a.suggestion_id };
    default:
      return {};
  }
};

/** How far the price has travelled from cost to the owner's target, 0..1. */
export const targetProgress = (avg, last, target) => {
  if (target == null || target === avg) return null;
  return Math.max(0, Math.min(1, (last - avg) / (target - avg)));
};

const VERDICT_ORDER = { SELL: 0, REVIEW: 1, HOLD: 2, ADD: 3, KEEP: 4 };
const KEYS = {
  weight: (r) => -(r.weight ?? r.weight_pct ?? 0),
  day: (r) => -(r.day_change_pct ?? 0),
  gain: (r) => -(r.pnl_pct ?? 0),
  verdict: (r) => VERDICT_ORDER[r.verdict] ?? 9,
};
export const sortHoldings = (rows, key = 'weight') => [...rows].sort((a, b) => KEYS[key](a) - KEYS[key](b));

export const formatXirr = (x) => (x == null ? '—' : `${(x * 100).toFixed(1)}%`);
