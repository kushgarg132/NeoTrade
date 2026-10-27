// Pulse helpers. Pure.

/**
 * Sector moves read off the scored news wire: each item's sector impacts
 * (`type: 'sector'`, signed `direction`, 0-10 `impact`) summed per sector.
 * Strongest net move first. There is no sector price feed; this is what the
 * news layer says each sector is doing.
 */
export const sectorRows = (items = [], limit = 6) => {
  const by = new Map();
  for (const item of items) {
    for (const i of item.impacts || []) {
      if (i.type !== 'sector' || !i.target || !Number.isFinite(i.impact) || !i.direction) continue;
      const row = by.get(i.target) || { sector: i.target, score: 0, count: 0 };
      row.score += Math.sign(i.direction) * i.impact;
      row.count += 1;
      by.set(i.target, row);
    }
  }
  return [...by.values()]
    .map((r) => ({ ...r, score: Math.round(r.score * 10) / 10 }))
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score) || a.sector.localeCompare(b.sector))
    .slice(0, limit);
};

export const DIVERGENCE_MIN = 0.3;

/**
 * A sector whose news and price disagree (`/market/scan` `sectors[]` row: `sentiment` -1..1 or null,
 * `change_pct`): 'good news, falling' / 'bad news, rising' when the signs differ and |sentiment| is at
 * least DIVERGENCE_MIN; else null (no sentiment, flat price, or weak news).
 */
export const divergence = ({ sentiment, change_pct: change } = {}) => {
  if (sentiment == null || change == null || Math.abs(sentiment) < DIVERGENCE_MIN || !change) return null;
  if (Math.sign(sentiment) === Math.sign(change)) return null;
  return sentiment > 0 ? 'good news, falling' : 'bad news, rising';
};

/** Advancing vs declining among quote rows (`percent`): breadth of whatever list it is given. */
export const breadth = (rows = []) => ({
  up: rows.filter((r) => r.percent > 0).length,
  down: rows.filter((r) => r.percent < 0).length,
});

/** Words for the up share of a breadth `{up, n}`; '' when there is no data. */
export const breadthWord = ({ up, n } = {}) => {
  if (!n) return '';
  const s = up / n;
  return s >= 0.7 ? 'Broad rally' : s >= 0.55 ? 'Leaning up' : s > 0.45 ? 'Mixed' : s > 0.3 ? 'Leaning down' : 'Broad sell-off';
};

export const impactWord = (n) => (n >= 7 ? 'High' : n >= 4 ? 'Med' : 'Low');

/** New array of `/market/scan` sector rows ordered by 'move' (|change_pct|), 'news' (sentiment, null last) or 'breadth' (up/n). */
export const sortSectors = (rows = [], by = 'move') => {
  const key = {
    move: (r) => Math.abs(r.change_pct ?? 0),
    news: (r) => r.sentiment ?? -Infinity,
    breadth: (r) => (r.n ? r.up / r.n : 0),
  }[by] || (() => 0);
  return [...rows].sort((a, b) => key(b) - key(a));
};

const IST_MS = 5.5 * 3600e3;

/** Splits news items into material ones published on/after IST midnight of `now` (pinned) and the rest. */
export const materialToday = (items = [], now = new Date()) => {
  const start = Math.floor((now.getTime() + IST_MS) / 864e5) * 864e5 - IST_MS;
  const pinned = [];
  const rest = [];
  for (const it of items) (it.material && Date.parse(it.published_at) >= start ? pinned : rest).push(it);
  return { pinned, rest };
};
