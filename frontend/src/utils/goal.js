// Goal tracker maths. Pure: `now` is passed in so tests do not depend on the clock.
const DAY = 86_400_000;
const MONTH = 30.44 * DAY;
const TOLERANCE = 0.0025; // a quarter of a percent a month either way still counts as "on" pace

const at = (d) => new Date(`${d}T00:00:00Z`).getTime();
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const monthlyRate = (from, to, months) => (from > 0 && to > 0 && months > 0 ? (to / from) ** (1 / months) - 1 : null);

/** The newest point at or before `time`; null when history starts later. */
const pointAt = (points, time) => [...points].reverse().find((p) => at(p.date) <= time) || null;

const pace = (needed, actual) => {
  if (needed == null || actual == null) return 'on';
  if (needed <= 0) return 'ahead'; // already there
  if (actual >= needed + TOLERANCE) return 'ahead';
  return actual >= needed - TOLERANCE ? 'on' : 'behind';
};

/**
 * goal: the saved prefs goal. overview: GET /mine/overview. history: GET /mine/history?range=ALL.
 * value: share of the way from start_value to target. beat_nifty: your edge over NIFTY on the
 * same rupees since `start` (value / nifty_value, so money added later does not count as skill)
 * against `target` percentage points. Monthly figures are fractions a month: for value the growth
 * needed from today's worth and the trailing 3 months' actual growth; for beat_nifty the extra
 * edge needed each month and the last 3 months' edge a month. Deposits count as growth (ceiling:
 * a big top-up reads as "ahead"; history has no cash-flow-free series).
 */
export const progress = (goal, overview, history, now = Date.now()) => {
  const none = { pct: 0, pace: 'on', neededMonthly: null, actualMonthly: null };
  const points = history?.points || [];
  const left = (at(goal.by) - now) / MONTH;
  const last = points[points.length - 1];

  if (goal.kind === 'beat_nifty') {
    if (!last?.nifty_value || !last.value) return none;
    const ratio = (p) => p.value / p.nifty_value;
    const base = pointAt(points, at(goal.start)) || points[0];
    const edge = ratio(last) / ratio(base) - 1;
    const goalEdge = goal.target / 100;
    const ago = pointAt(points, now - 3 * MONTH);
    const actual = ago && ago.nifty_value ? (ratio(last) / ratio(ago) - 1) / 3 : null;
    const needed = left > 0 ? (goalEdge - edge) / left : goalEdge - edge > 0 ? Infinity : 0;
    return { pct: clamp01(edge / goalEdge), pace: pace(needed, actual), neededMonthly: needed, actualMonthly: actual };
  }

  const cur = overview?.headline?.value;
  if (typeof cur !== 'number') return none;
  const from = goal.start_value;
  const share = from != null && goal.target > from ? (cur - from) / (goal.target - from) : cur / goal.target;
  const needed = cur >= goal.target ? 0 : left > 0 ? monthlyRate(cur, goal.target, left) : Infinity;
  const ago = pointAt(points, now - 3 * MONTH);
  const actual = ago && last ? monthlyRate(ago.value, cur, (now - at(ago.date)) / MONTH) : null;
  return { pct: clamp01(share), pace: pace(needed, actual), neededMonthly: needed, actualMonthly: actual };
};
