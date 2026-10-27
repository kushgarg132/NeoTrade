const HORIZONS = ['1h', '1d', '5d'];

/** news_outcomes rows -> one entry per measured (target, horizon). `move` is the target's return,
 *  `vsBench` that minus Nifty's. Unmeasured horizons are skipped; no outcomes is []. */
export const outcomeRows = (outcomes) => (outcomes || []).flatMap((o) => HORIZONS
  .filter((h) => o[`ret_${h}`] != null && o[`bench_${h}`] != null)
  .map((h) => ({ target: o.target, horizon: h, move: o[`ret_${h}`], vsBench: o[`ret_${h}`] - o[`bench_${h}`] })));
