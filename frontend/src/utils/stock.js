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

const IST_MS = 5.5 * 3600 * 1000;
export const NEWS_MARKER_CAP = 200;

/**
 * Material news on a price series (GET /news/symbol/{symbol} `items`), one marker per trading day.
 * An item lands on the first close on or after its IST date (weekend / after-hours news shows on the
 * session it could move), news after the last close lands on the last close, news before the first is
 * dropped. Same-day items collapse: `count`, `impact` = the largest, `direction` = sign of the summed
 * direction x impact (0 = mixed), `items` newest first. More than `cap` days keeps the most impactful.
 */
export const newsMarkers = (data, items, cap = NEWS_MARKER_CAP) => {
  if (!data?.length || !items?.length) return [];
  const dates = data.map((d) => d.date);
  const byDate = new Map();
  for (const it of items) {
    if (!it.material || !it.published_at) continue;
    const day = new Date(new Date(it.published_at).getTime() + IST_MS).toISOString().slice(0, 10);
    if (day < dates[0]) continue;
    let lo = 0;
    let hi = dates.length - 1;
    while (lo < hi) { // first date >= day, else the last one
      const mid = (lo + hi) >> 1;
      if (dates[mid] >= day) hi = mid; else lo = mid + 1;
    }
    const m = byDate.get(dates[lo]) || { date: dates[lo], price: data[lo].close, items: [], net: 0, impact: 0 };
    m.items.push(it);
    m.net += (it.direction || 0) * (it.impact || 0);
    m.impact = Math.max(m.impact, it.impact || 0);
    byDate.set(dates[lo], m);
  }
  let out = [...byDate.values()];
  if (out.length > cap) out = out.sort((a, b) => b.impact - a.impact).slice(0, cap);
  return out
    .map(({ net, ...m }) => ({
      ...m,
      count: m.items.length,
      direction: Math.sign(net),
      items: m.items.sort((a, b) => String(b.published_at).localeCompare(String(a.published_at))),
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
};

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
