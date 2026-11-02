// The index page's Stocks tab: sorting and the up/down count. Pure.

export const SORTS = [['gain', 'Gainers'], ['fall', 'Losers'], ['name', 'A–Z']];

/** A stock with no quote always sorts last, whichever way the moves run. */
export const sortStocks = (rows, sort) => [...(rows || [])].sort((a, b) => {
  if (sort === 'name') return a.symbol.localeCompare(b.symbol);
  if (a.change_pct == null || b.change_pct == null) return (a.change_pct == null) - (b.change_pct == null);
  return sort === 'fall' ? a.change_pct - b.change_pct : b.change_pct - a.change_pct;
});

export const upDown = (rows) => ({
  up: (rows || []).filter((r) => r.change_pct > 0).length,
  down: (rows || []).filter((r) => r.change_pct < 0).length,
});
