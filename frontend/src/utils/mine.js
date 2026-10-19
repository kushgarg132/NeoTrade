/** Helpers for the Mine pages (Overview, Holdings, Stock, Tax). */
import { stockPath } from './stocks.js';

export const RANGES = ['1M', '6M', '1Y', 'ALL'];
export const rangeLabel = (r) => (r === 'ALL' ? 'All' : r);

/** Where a Needs-you row leads: a page, an order ticket, or an idea to decide. */
export const actionTarget = (item) => {
  const a = item?.action || {};
  switch (a.type) {
    case 'stock':
      return { to: stockPath(item.symbol) };
    case 'tax':
      return { to: '/portfolio/tax' };
    case 'rebalance':
      return { to: '/portfolio/holdings?plan=1' };
    case 'ticket':
      return { ticket: { symbol: item.symbol, side: a.side, quantity: a.quantity, limitPrice: a.price } };
    case 'idea':
      return { to: '/portfolio', idea: a.suggestion_id };
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

/** Holdings older than 36h mean the broker is logged out (same rule as Today). */
export const STALE_MS = 36 * 3_600_000;
export const holdingsStale = (holdingsAsOf, now = Date.now()) =>
  Boolean(holdingsAsOf) && now - new Date(holdingsAsOf) > STALE_MS;

/** The Tax page's FYs: the current one back to FY 2025-26 (earlier years had other rates). */
export const TAX_FIRST_FY = 2025;
export const taxYears = (current) => {
  const out = [];
  for (let fy = current; fy >= TAX_FIRST_FY; fy -= 1) out.push(fy);
  return out.length ? out : [TAX_FIRST_FY];
};

/** Plain-English text for each verdict reason code. */
export const REASONS = {
  loss_beyond_limit: 'Further below its cost than your loss limit',
  earnings_falling_3q: 'Profit fell in each of the last three quarters',
  earnings_rising_3q: 'Profit rose in each of the last three quarters',
  below_200dma: 'Price is under its 200-day average',
  uptrend: 'Price above its 50-day average, which is above its 200-day',
  overweight: 'A bigger share of your portfolio than your size limit',
  high_debt: 'Debt is more than twice equity',
  strong_roe: 'Return on equity of 15% or more',
  reasonable_valuation: 'Price to earnings under 40',
};
