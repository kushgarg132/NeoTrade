/** The news accuracy report (GET /news/accuracy): cells -> table rows for the Lab page. */

export const SCOPES = ['COMPANY', 'SECTOR', 'MARKET', 'MACRO', 'GLOBAL'];
export const HORIZONS = ['1d', '5d', '20d'];
export const MEASURES = { move: 'vs NIFTY', pre_move: 'vs NIFTY, from pre-news close', sector_move: 'vs sector peers' };
const IMPACT_ORDER = { all: 0, '<5': 1, '5-7': 2, '>=7': 3 };
const GROUP_ORDER = { theme: 0, source: 1, model: 2 };

/** One scope and horizon's cells: the total first, then themes, sources, models (A-Z). */
export const rowsFor = (cells, scope, horizon) => (cells || [])
  .filter((c) => c.scope === scope && c.horizon === horizon)
  .sort((a, b) => (GROUP_ORDER[a.group] - GROUP_ORDER[b.group])
    || ((a.key === 'all' ? 0 : 1) - (b.key === 'all' ? 0 : 1))
    || a.key.localeCompare(b.key)
    || (IMPACT_ORDER[a.impact] - IMPACT_ORDER[b.impact])
    || Object.keys(MEASURES).indexOf(a.measure) - Object.keys(MEASURES).indexOf(b.measure));

/** Green above 52%, red below 48%, plain around a coin flip; thin cells stay plain. */
export const hitTone = (cell) => (cell.thin || cell.hit == null ? 'neutral'
  : cell.hit >= 0.52 ? 'gain' : cell.hit <= 0.48 ? 'loss' : 'neutral');
