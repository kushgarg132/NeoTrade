// What the news layer says about a stock, for list pages (GET /news/symbols).
import { newsLean } from './stock.js';

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

/** The IST calendar day ("2026-10-26") of a timestamp, or null. */
export const istDay = (at) => {
  const t = at == null ? null : new Date(at);
  return t && !Number.isNaN(t.getTime()) ? t.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }) : null;
};

/** A material headline published today (IST). */
export const newsToday = (entry, now = Date.now()) =>
  !!entry?.material && !!entry.published_at && istDay(entry.published_at) === istDay(now);

/** Any scored headline in the window /news/symbols covers (72h). */
export const hasNews = (entry) => !!entry?.headline;

/** A pick's "bad news since signal": a strong negative item (direction <= -0.5, impact >= 7) dated after the
 * IST day it fired. Reads only the stock's latest material item, so a later good one can hide an older bad one. */
export const badNewsSince = (entry, firedOn) => !!firedOn && finite(entry?.direction) && entry.direction <= -0.5
  && finite(entry.impact) && entry.impact >= 7 && (istDay(entry.published_at) || '') > firedOn;

/** "Results in 6 days" when the next results date (YYYY-MM-DD) falls inside the idea's horizon
 * (trading days, read as horizon × 7/5 calendar days), else null. */
export const resultsFlag = (date, horizon, now = Date.now()) => {
  const today = istDay(now);
  if (!date || !today || !finite(horizon)) return null;
  const days = Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86400000);
  if (!(days >= 0) || days > Math.ceil((horizon * 7) / 5)) return null;
  return days === 0 ? 'Results today' : `Results in ${days} day${days === 1 ? '' : 's'}`;
};

/** Why a loss-harvest candidate is down: fresh (72h) material negative news, or not. */
export const lossCause = (entry) => (badNews(entry)
  ? { news: true, text: `Drop after news: ${entry.headline || 'material bad news'}` }
  : { news: false, text: 'Slow decline' });

/** A refreshed first page in front of the already-loaded list, deduped by id (paged items are kept). */
export const mergeFront = (cur, fresh) => {
  const ids = new Set(fresh.map((n) => n.id));
  return [...fresh, ...(cur || []).filter((n) => !ids.has(n.id))];
};

/** A feed item whose strongest impact points `lean` ('up' | 'down'); '' keeps every item. */
export const matchLean = (item, lean) => {
  if (!lean) return true;
  const d = newsLean(item).direction;
  return lean === 'up' ? d > 0 : d < 0;
};

/** Feed items (newest first) under IST-day headers: [{ day, label, items }], label 'Today' / 'Yesterday' / 'Thu 29 Oct'. */
export const byDay = (items = [], now = Date.now()) => {
  const today = istDay(now);
  const yesterday = istDay(Date.parse(`${today}T12:00:00Z`) - 864e5);
  const groups = new Map();
  for (const it of items) {
    const day = istDay(it.published_at);
    if (!day) continue;
    if (!groups.has(day)) {
      const label = day === today ? 'Today' : day === yesterday ? 'Yesterday'
        : new Date(`${day}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
      groups.set(day, { day, label, items: [] });
    }
    groups.get(day).items.push(it);
  }
  return [...groups.values()].sort((a, b) => (a.day < b.day ? 1 : -1));
};
