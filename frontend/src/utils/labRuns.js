const SUMMARY = ['cagr', 'sharpe', 'sortino', 'max_drawdown', 'volatility', 'alpha', 'beta'];
const num = (v) => typeof v === 'number' && Number.isFinite(v);

const nums = (o) => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => num(v)));

/** One flat object of numeric metrics from any run kind's payload (gate summary, factor oos, retune test/best, builder, study). */
export const flatMetrics = (m) => {
  m = m || {};
  const oos = m.oos?.summary ?? m.oos;
  const out = { ...nums(m), ...nums(m.summary), ...nums(oos) };
  if (!num(out.volatility) && num(out.vol)) out.volatility = out.vol; // factor report names it vol
  const fb = nums(m.test?.summary ?? m.test?.best ?? m.train?.summary); // retune: out-of-sample best variant
  for (const k of Object.keys(fb)) if (!(k in out)) out[k] = fb[k];
  return out;
};

/** Side-by-side rows for two runs: the summary keys first, then other numeric keys both runs have. */
export const compareRows = (a, b) => {
  const ma = flatMetrics(a?.metrics);
  const mb = flatMetrics(b?.metrics);
  const both = (k) => num(ma[k]) && num(mb[k]);
  const extra = Object.keys(ma).filter((k) => !SUMMARY.includes(k) && both(k));
  return [...SUMMARY.filter(both), ...extra].map((key) => ({ key, a: ma[key], b: mb[key] }));
};

const PCT = ['cagr', 'max_drawdown', 'volatility', 'alpha'];
const TWO = ['sharpe', 'sortino', 'beta'];
/** Percent for return-like keys, 2 dp for ratios, 3 dp otherwise; "—" when not a number. */
export const fmtMetric = (key, v) => {
  if (!num(v)) return '—';
  if (PCT.includes(key)) return `${(v * 100).toFixed(1)}%`;
  return v.toFixed(TWO.includes(key) ? 2 : 3);
};
