// One view model for the Ideas screens: a stored suggestion or a Picks row.
import { strategyName } from './library.js';

/** Route id: `s-<suggestionId>` or `p-<pickId>` (pick ids hold colons, so only the first dash splits). */
export const parseIdeaId = (id) => {
  const m = /^([sp])-(.+)$/.exec(id || '');
  return m ? { kind: m[1], key: m[2] } : null;
};

/** The suggestion's composite score ({rule, ai, final}, 0-1): the rules' part and what the AI added on top. */
export const confidence = (score) => (score && typeof score.final === 'number'
  ? { final: score.final, rule: score.rule ?? null, ai: score.rule != null ? score.final - score.rule : null }
  : null);

export const ideaFromSuggestion = (s) => {
  const entry = s.entry_ref;
  const risk = s.stop != null && entry != null ? Math.abs(entry - s.stop) * s.quantity : null;
  const gain = s.target != null && entry ? (s.target - entry) / entry : null;
  return {
    id: `s-${s.id}`, kind: 's', symbol: s.symbol, side: s.side,
    setup: strategyName(s.strategy) || 'Idea', horizon: s.max_hold_days ?? null,
    headline: gain == null ? null : { label: 'to target', value: s.side === 'SELL' ? -gain : gain },
    badge: s.strategy ? { source: 'suggestion', name: s.strategy } : null,
    entry, stop: s.stop ?? null, target: s.target ?? null,
    qty: s.quantity, notional: s.notional ?? (entry ? entry * s.quantity : null), risk,
    reasons: (s.reason_codes || []).map(strategyName), thesis: s.ai_thesis || null, createdAt: s.created_at || null, why: null,
    range: null, pUp: null, pBeat: null, pastN: null, oosExcess: null, oosN: null, decided: s.status !== 'PENDING',
    status: s.status, strategy: s.strategy || null, score: confidence(s.score),
    toStop: s.stop != null && entry ? -Math.abs(entry - s.stop) / entry : null,
  };
};

/** "20 Nov" from a date-only string (IST date, so pin to UTC and never shift it). */
export const dueLabel = (d) => {
  const t = d ? new Date(`${d}T00:00:00Z`) : null;
  return t && !Number.isNaN(t.getTime()) ? t.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }) : null;
};

/** "in 20 trading days · by 20 Nov" (either half may be missing). */
export const whenLabel = (horizon, due) => {
  const d = dueLabel(due);
  const h = horizon ? `in ${horizon} trading day${horizon === 1 ? '' : 's'}` : null;
  return [h, d && `by ${d}`].filter(Boolean).join(' · ') || null;
};

/** Expected move per share: "≈ ₹5.7 on ₹522.9" (null without an entry price or a median). */
export const rupeeMove = (entry, median) => {
  if (typeof entry !== 'number' || typeof median !== 'number' || !entry) return null;
  const m = entry * median;
  return `≈ ${m < 0 ? '−' : '+'}₹${Math.abs(m).toFixed(1)} on ₹${entry.toFixed(1)}`;
};

/** "fired Mon · now +0.8% from entry · 14 days left" for a pick from an earlier day (null for today's). */
export const olderPickLabel = (idea) => {
  if (!idea?.daysSince || !idea.firedOn) return null;
  const t = new Date(`${idea.firedOn}T00:00:00Z`);
  const day = Number.isNaN(t.getTime()) ? null : t.toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' });
  const m = idea.moveSinceEntry;
  return [day && `fired ${day}`,
    typeof m === 'number' && `now ${m < 0 ? '−' : '+'}${Math.abs(m * 100).toFixed(1)}% from entry`,
    idea.daysLeft != null && `${idea.daysLeft} day${idea.daysLeft === 1 ? '' : 's'} left`].filter(Boolean).join(' · ') || null;
};

/** Copy for the New ideas card when nothing is served. */
export const noPickText = (hiddenReason) => ({
  title: 'No pick worth taking today',
  body: hiddenReason ? `${hiddenReason}. Past ones are in History.` : 'Nothing has an edge over NIFTY. Past ones are in History.',
});

export const ideaFromPick = (p, setup) => {
  const ex = p.expected?.excess;
  const exMedian = ex?.median ?? p.median_excess ?? null;
  return {
    id: `p-${p._id}`, kind: 'p', symbol: p.symbol, side: 'BUY',
    setup: p.label, horizon: p.horizon,
    headline: typeof p.expected?.median === 'number' ? { label: (p.days_since > 0 ? dueLabel(p.due_date) && `by ${dueLabel(p.due_date)}` : whenLabel(p.horizon, p.due_date)) || 'expected', value: p.expected.median }
      : exMedian != null ? { label: 'vs NIFTY', value: exMedian } : { label: 'median', value: null },
    expectedMedian: p.expected?.median ?? null, when: whenLabel(p.horizon, p.due_date), exMedian,
    // Prefer a per-stock range when the backend sends one (expected.range_stock), else the forecast's p10/p90.
    spread: p.expected ? { p10: p.expected.range_stock?.p10 ?? p.expected.p10, p90: p.expected.range_stock?.p90 ?? p.expected.p90 } : null,
    rupees: rupeeMove(p.entry_ref, p.expected?.median),
    badge: { source: 'picks', name: p.setup },
    entry: p.entry_ref, stop: null, target: null, qty: null, notional: null, risk: null,
    reasons: [], thesis: null, why: p.explanation || null,
    range: p.expected ? { p10: p.expected.p10, median: p.expected.median, p90: p.expected.p90 } : null,
    excessRange: ex ? { p10: ex.p10, median: ex.median, p90: ex.p90 } : null,
    forecast: p.forecast || null, similarN: p.similar_n ?? null, features: describeFeatures(p.features),
    pUp: p.p_up, pBeat: p.p_beat_nifty, pastN: p.n,
    oosExcess: setup?.walk_forward?.oos_excess ?? null, oosN: setup?.walk_forward?.oos_n ?? null,
    noEdge: p.edge === false, decided: false,
    firedOn: p.fired_on ?? null, daysSince: p.days_since ?? 0, daysLeft: p.days_left ?? null, moveSinceEntry: p.move_since_entry ?? null,
  };
};

/** The six similarity features of a pick in plain words (missing values are skipped). */
export const describeFeatures = (f) => {
  if (!f) return [];
  const out = [];
  const add = (v, rules) => { if (typeof v === 'number') out.push(rules.find(([t]) => v > t)[1]); };
  add(f.dist_high, [[-0.03, 'near its 52-week high'], [-0.15, 'a bit below its 52-week high'], [-Infinity, 'well below its 52-week high']]);
  add(f.vol60, [[0.025, 'more volatile than usual'], [0.015, 'normal volatility'], [-Infinity, 'calmer than usual']]);
  add(f.mom, [[0.1, 'strong momentum'], [-0.05, 'flat momentum'], [-Infinity, 'losing momentum']]);
  add(f.rel20, [[0.02, 'beating NIFTY over the last month'], [-0.02, 'in line with NIFTY lately'], [-Infinity, 'lagging NIFTY over the last month']]);
  // strength is on each setup's own scale, so it has no plain-word reading here.
  // regime = NIFTY / its 200-day mean - 1 (backend/forecast/similar.py::_frames).
  add(f.regime, [[0.02, 'market in an uptrend'], [-0.02, 'market sideways'], [-Infinity, 'market in a downtrend']]);
  return out;
};

/** Positions (0-100) of p10 / median / p90 and the zero line on a track that always contains zero. */
export const rangeBar = (p10, median, p90) => {
  const lo = Math.min(p10, 0);
  const hi = Math.max(p90, 0);
  const span = hi - lo;
  const at = (x) => (span > 0 ? Math.max(0, Math.min(100, ((x - lo) / span) * 100)) : 50);
  return { p10: at(p10), median: at(median), p90: at(p90), zero: at(0) };
};

/** Plain titles for the "Your holdings" groups on Ideas, in the order /mine/actions ranks them. */
export const HOLDING_GROUPS = {
  stop_hit: 'Exit alerts', idea_exit: 'Exit alerts', target_hit: 'Exit alerts',
  verdict_worse: 'Verdict got worse', bad_news: 'Bad news', review_due: 'Reviews due',
  results_soon: 'Results soon', overweight: 'Too much in one stock', ltcg_soon: 'Tax: turning long-term',
  harvest: 'Tax: harvest', ex_dividend: 'Dividends coming', add: 'Room to add',
};

/** Mine actions about the holdings: everything except `idea` rows, which are the Ideas list's own pending suggestions. */
export const holdingActions = (actions) => (Array.isArray(actions) ? actions : []).filter((a) => a.kind !== 'idea');

/** [{ title, items }] in rank order, one group per plain title. */
export const groupHoldingActions = (actions) => {
  const groups = [];
  for (const a of holdingActions(actions)) {
    const title = HOLDING_GROUPS[a.kind] || 'Other';
    let g = groups.find((x) => x.title === title);
    if (!g) groups.push((g = { title, items: [] }));
    g.items.push(a);
  }
  return groups;
};

/** The ONE "needs you" number: holdings actions plus pending ideas (your suggestions, and today's Picks for admins). */
export const needCount = (actions, ideas) =>
  holdingActions(actions).length + (Array.isArray(ideas) ? ideas.length : 0);
