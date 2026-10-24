/** The one look every recharts chart, gauge and heatmap shares. Tokens only (index.css). */

/** Categorical series colours, assigned in this order and never cycled. Light mode's
 *  slots 3-5 sit below 3:1 on white, so a chart using them shows a legend or direct labels. */
export const SERIES = [1, 2, 3, 4, 5, 6].map((n) => `var(--chart-${n})`);

/** Spread onto <XAxis> / <YAxis>. */
export const AXIS = {
  tick: { fontSize: 12, fill: 'var(--text-muted)' },
  tickLine: false,
  axisLine: { stroke: 'var(--border)' },
};

/** Spread onto <CartesianGrid>. */
export const GRID = { stroke: 'var(--border)', vertical: false };

/** contentStyle for recharts' default <Tooltip>. */
export const TOOLTIP_STYLE = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: 12,
  fontSize: 13,
  color: 'var(--text)',
};

/** A % change as a diverging heat cell: three steps each side of a neutral band (|pct| < maxAbs/12).
 *  Colour is never the only carrier: cells also print the signed %. */
export const heatColor = (pct, maxAbs = 3) => {
  const v = Number(pct);
  if (!Number.isFinite(v) || Math.abs(v) < maxAbs / 12) return 'var(--heat-0)';
  const step = Math.abs(v) < maxAbs / 3 ? 1 : Math.abs(v) < (2 * maxAbs) / 3 ? 2 : 3;
  return `var(--heat-${v > 0 ? 'pos' : 'neg'}-${step})`;
};
