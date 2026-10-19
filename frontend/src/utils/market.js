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

/** Advancing vs declining among quote rows (`percent`): breadth of whatever list it is given. */
export const breadth = (rows = []) => ({
  up: rows.filter((r) => r.percent > 0).length,
  down: rows.filter((r) => r.percent < 0).length,
});
