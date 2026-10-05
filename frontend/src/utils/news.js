// What the news layer says about a stock, for list pages (GET /news/symbols).

const finite = (x) => typeof x === 'number' && Number.isFinite(x);
const BAND = 0.2;

/** 'pos' | 'neg' | 'flat' from sentiment, else from the headline's direction; null without either. */
export const tone = (entry) => {
  if (!entry) return null;
  const value = finite(entry.sentiment) ? entry.sentiment : finite(entry.direction) ? entry.direction : null;
  if (value === null) return null;
  return value >= BAND ? 'pos' : value <= -BAND ? 'neg' : 'flat';
};

/** "News +0.4" / "News −0.6" (signed, true minus) or just "News". */
export const chipLabel = (entry) => {
  if (!entry || !finite(entry.sentiment)) return 'News';
  const v = entry.sentiment;
  return `News ${v < 0 ? '−' : '+'}${Math.abs(v).toFixed(1)}`;
};

export const hasRecentNews = (entry, hours = 24, now = Date.now()) => {
  const at = entry?.published_at ? Date.parse(entry.published_at) : Number.NaN;
  return Number.isFinite(at) && now - at <= hours * 3600 * 1000;
};

const badNews = (entry) => !!entry?.material && finite(entry.direction) && entry.direction < 0;

/** Holdings hit by material negative news first; the rest keep their order. */
export const sortByNewsRisk = (rows, newsBySymbol = {}) => {
  const hit = rows.filter((r) => badNews(newsBySymbol[r.symbol]));
  return [...hit, ...rows.filter((r) => !badNews(newsBySymbol[r.symbol]))];
};
