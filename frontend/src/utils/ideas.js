// One view model for the Ideas screens: a stored suggestion or a Picks row.
import { strategyName } from './library.js';

/** Route id: `s-<suggestionId>` or `p-<pickId>` (pick ids hold colons, so only the first dash splits). */
export const parseIdeaId = (id) => {
  const m = /^([sp])-(.+)$/.exec(id || '');
  return m ? { kind: m[1], key: m[2] } : null;
};

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
