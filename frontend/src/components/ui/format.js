// Number formatting for the redesign. Pure; nothing here touches the DOM.
const num = (n) => (typeof n === 'number' && Number.isFinite(n) ? n : null);
const sgn = (n, on) => (n < 0 ? '-' : on && n > 0 ? '+' : '');

/** ₹ with Indian digit grouping: inr(409205) = "₹4,09,205". `sign` adds "+" to gains. */
export const inr = (n, { sign = false } = {}) => {
  const v = num(n);
  if (v === null) return '—';
  const body = Math.abs(Math.round(v)).toLocaleString('en-IN');
  return `${sgn(Math.round(v), sign)}₹${body}`;
};

/** A fraction as a percent: pct(0.0165, {sign:true}) = "+1.65%". */
export const pct = (x, { sign = false, dp = 2 } = {}) => {
  const v = num(x);
  if (v === null) return '—';
  const p = Number((v * 100).toFixed(dp));
  return `${sgn(p, sign)}${Math.abs(p).toFixed(dp)}%`;
};

export const tone = (x) => (num(x) === null || x === 0 ? 'neutral' : x > 0 ? 'gain' : 'loss');

/** Lakh/crore shorthand: ₹4.09L, ₹1.2Cr. Under a lakh it is the plain figure. */
export const compactInr = (n) => {
  const v = num(n);
  if (v === null) return '—';
  const a = Math.abs(v);
  const trim = (x, dp) => String(Number(x.toFixed(dp)));
  if (a >= 1e7) return `${sgn(v, false)}₹${trim(a / 1e7, a >= 1e8 ? 1 : 2)}Cr`;
  if (a >= 1e5) return `${sgn(v, false)}₹${a / 1e5 >= 100 ? trim(a / 1e5, 1) : (a / 1e5).toFixed(2)}L`;
  return inr(v);
};

/** Index/price level, no currency: points(24812.5, {sign:true}) = "+24,812.5". Up to 2 dp. */
export const points = (n, { sign = false } = {}) => {
  const v = num(n);
  if (v === null) return '—';
  const r = Number(v.toFixed(2));
  return `${sgn(r, sign)}${Math.abs(r).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
};
