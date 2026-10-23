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

/**
 * Investing.com-style technical summary over the snapshot's indicators (GET quick-analyze `technical_analysis`):
 * each reading is bullish, bearish or neutral. Worded as a reading of the indicators, never as "buy" or "sell".
 */
export const techSummary = (t) => {
  if (!t || typeof t.price !== 'number') return null;
  const vs = (name, a, b) => (typeof a === 'number' && typeof b === 'number' ? { name, read: a > b ? 'bull' : a < b ? 'bear' : 'neutral' } : null);
  const rsi = typeof t.rsi === 'number'
    ? { name: `RSI ${t.rsi.toFixed(0)}`, read: t.rsi > 70 || t.rsi < 30 ? 'neutral' : t.rsi >= 50 ? 'bull' : 'bear' }
    : null;
  const rows = [
    vs('Price vs 20-day EMA', t.price, t.ema_20),
    vs('Price vs 50-day average', t.price, t.sma_50),
    vs('Price vs 200-day average', t.price, t.sma_200),
    vs('50-day vs 200-day average', t.sma_50, t.sma_200),
    vs('MACD vs signal', t.macd, t.macd_signal),
    rsi,
  ].filter(Boolean);
  if (!rows.length) return null;
  const bull = rows.filter((r) => r.read === 'bull').length;
  const bear = rows.filter((r) => r.read === 'bear').length;
  const net = bull - bear;
  const label = net >= 3 ? 'Mostly bullish' : net >= 1 ? 'Leaning bullish' : net <= -3 ? 'Mostly bearish' : net <= -1 ? 'Leaning bearish' : 'Mixed';
  return { rows, bull, bear, neutral: rows.length - bull - bear, label, tone: net > 0 ? 'gain' : net < 0 ? 'loss' : 'neutral' };
};
