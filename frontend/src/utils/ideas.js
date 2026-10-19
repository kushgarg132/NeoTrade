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
    reasons: (s.reason_codes || []).map(strategyName), thesis: s.ai_thesis || null, why: null,
    range: null, pUp: null, pBeat: null, pastN: null, oosExcess: null, oosN: null, decided: s.status !== 'PENDING',
    status: s.status, strategy: s.strategy || null, score: confidence(s.score),
    toStop: s.stop != null && entry ? -Math.abs(entry - s.stop) / entry : null,
  };
};

export const ideaFromPick = (p, setup) => ({
  id: `p-${p._id}`, kind: 'p', symbol: p.symbol, side: 'BUY',
  setup: p.label, horizon: p.horizon,
  headline: { label: 'median', value: p.expected?.median ?? null },
  badge: { source: 'picks', name: p.setup },
  entry: p.entry_ref, stop: null, target: null, qty: null, notional: null, risk: null,
  reasons: [], thesis: null, why: p.explanation || null,
  range: p.expected ? { p10: p.expected.p10, median: p.expected.median, p90: p.expected.p90 } : null,
  pUp: p.p_up, pBeat: p.p_beat_nifty, pastN: p.n,
  oosExcess: setup?.walk_forward?.oos_excess ?? null, oosN: setup?.walk_forward?.oos_n ?? null,
  noEdge: p.edge === false, decided: false,
});

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
