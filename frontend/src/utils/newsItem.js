const HORIZONS = ['1h', '1d', '5d'];

// The ingest worker's feed ids (backend/datalayer/news_sources.py) by publisher; other sources are already names.
const PUBLISHERS = { et: 'Economic Times', bs: 'Business Standard', hbl: 'BusinessLine', mint: 'Mint', rbi: 'RBI', sebi: 'SEBI',
  pib: 'PIB', cnbc: 'CNBC', bbc: 'BBC', gnews: 'Google News' };

/** "hbl_markets" -> "BusinessLine"; a source that is not a feed id comes back as it is. */
export const sourceName = (s) => (/^[a-z]+_[a-z_]+$|^[a-z]+$/.test(s || '') ? PUBLISHERS[s.split('_')[0]] || s : s);

const FLAT = 0.003; // within ±0.3% of the Nifty (of nothing, for the market itself) is no move either way

/** One entry per target the scorer named: its call (direction, impact, horizon), what it did at each measured
 *  horizon (`move`, `edge` = vs Nifty for a stock or sector, the move itself for the market), and the verdict at
 *  the longest measured horizon: 'right' (edge the called way), 'wrong', 'flat' or 'pending'. Pure. */
export const targetCalls = (item) => {
  const outs = Object.fromEntries((item?.outcomes || []).map((o) => [`${o.type}:${o.target}`, o]));
  return (item?.impacts || []).slice().sort((a, b) => (b.impact ?? 0) - (a.impact ?? 0)).map((i) => {
    const o = outs[`${i.type}:${i.target}`] || {};
    const moves = HORIZONS.map((h) => {
      const move = o[`ret_${h}`];
      const bench = o[`bench_${h}`];
      if (move == null || bench == null) return { h, move: null, edge: null };
      return { h, move, edge: i.type === 'market' ? move : move - bench };
    });
    const last = [...moves].reverse().find((m) => m.edge != null);
    const verdict = !last ? 'pending' : Math.abs(last.edge) < FLAT || !i.direction ? 'flat'
      : Math.sign(last.edge) === Math.sign(i.direction) ? 'right' : 'wrong';
    return { ...i, moves, verdict, at: last?.h ?? null };
  });
};
