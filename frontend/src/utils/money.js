// Pure helpers for the Money area (Holdings list and Overview movers).
import { REASONS } from './mine.js';

const fin = (x) => typeof x === 'number' && Number.isFinite(x);

/** Today's move as a fraction (0.012 = +1.2%) from last vs previous close; null without both. */
export const dayFraction = (h) => (fin(h.last_price) && fin(h.close_price) && h.close_price ? h.last_price / h.close_price - 1 : null);

/** Today's move in rupees for the shares held; null without a price pair and a quantity. */
export const dayRupees = (h) => (fin(h.last_price) && fin(h.close_price) && fin(h.quantity) ? (h.last_price - h.close_price) * h.quantity : null);

const KEYS = {
  day: (h) => h.day_pct ?? dayFraction(h),
  value: (h) => h.value,
  weight: (h) => h.weight_pct,
  pnl: (h) => h.pnl_pct,
};

/** Biggest first by `day` | `value` | `weight` | `pnl`; rows missing the figure sink to the bottom. */
export const sortHoldings = (rows, key = 'value') => {
  const get = KEYS[key] || KEYS.value;
  const v = (h) => (fin(get(h)) ? get(h) : -Infinity);
  return [...rows].sort((a, b) => v(b) - v(a));
};

/** The `n` holdings that moved most today in rupees, as {...holding, day_pct, day_rupees}. Funds and unpriced rows are skipped. */
export const topMovers = (rows, n = 3) =>
  rows
    .map((h) => ({ ...h, day_pct: dayFraction(h), day_rupees: dayRupees(h) }))
    .filter((h) => h.day_rupees != null && h.day_rupees !== 0)
    .sort((a, b) => Math.abs(b.day_rupees) - Math.abs(a.day_rupees))
    .slice(0, n);

export const MARKET_WHY = 'Moved with the market';

/** One line on why a holding is where it is: its latest headline, else its verdict reason, else the fallback. */
export const whyLine = (h) => {
  const headline = h?.news?.headline;
  if (headline) return headline;
  const code = (h?.reason_codes || []).find((c) => REASONS[c]);
  return code ? REASONS[code] : MARKET_WHY;
};

/** A holding type in words. ETFs and funds are a type, never a sector. */
export const KIND_LABEL = { STOCK: 'Stocks', ETF: 'ETFs', MF: 'Mutual funds' };
export const kindLabel = (kind) => KIND_LABEL[kind] || kind;

/** The allocation strip: the `top` largest holdings by weight, then the rest as one "Others" slice;
 *  [{ label, pct }] in percent, largest first. Pure. */
export const allocation = (holdings = [], top = 6) => {
  const rows = holdings.filter((h) => typeof h.weight_pct === 'number' && h.weight_pct > 0)
    .sort((a, b) => b.weight_pct - a.weight_pct);
  const out = rows.slice(0, top).map((h) => ({ label: h.kind === 'MF' ? h.name || h.symbol : h.symbol, pct: h.weight_pct }));
  const rest = rows.slice(top).reduce((s, h) => s + h.weight_pct, 0);
  return rest > 0.05 ? [...out, { label: `${rows.length - top} others`, pct: rest }] : out;
};

/** /mine/overview `drivers[period]` as one list for diverging bars: the gainers then the losers, each with
 *  `share` = |contribution| / the largest |contribution| (0..1). Pure. */
export const driverRows = (d) => {
  const rows = [...(d?.top || []), ...(d?.bottom || [])].filter((r) => typeof r.contribution === 'number');
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.contribution)));
  return rows.map((r) => ({ ...r, share: Math.abs(r.contribution) / max }));
};
