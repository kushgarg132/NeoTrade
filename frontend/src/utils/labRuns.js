const SUMMARY = ['cagr', 'sharpe', 'sortino', 'max_drawdown', 'volatility', 'alpha', 'beta'];
const num = (v) => typeof v === 'number' && Number.isFinite(v);

/** Side-by-side rows for two runs: the summary keys first, then other numeric keys both runs have. */
export const compareRows = (a, b) => {
  const ma = a?.metrics || {};
  const mb = b?.metrics || {};
  const both = (k) => num(ma[k]) && num(mb[k]);
  const extra = Object.keys(ma).filter((k) => !SUMMARY.includes(k) && both(k));
  return [...SUMMARY.filter(both), ...extra].map((key) => ({ key, a: ma[key], b: mb[key] }));
};
