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
  return [day && `${idea.backfilled ? 'recomputed for' : 'fired'} ${day}`,
    typeof m === 'number' && `now ${m < 0 ? '−' : '+'}${Math.abs(m * 100).toFixed(1)}% from entry`,
    idea.missedEntry && 'past the entry zone',
    idea.daysLeft != null && `${idea.daysLeft} day${idea.daysLeft === 1 ? '' : 's'} left`].filter(Boolean).join(' · ') || null;
};

/** A pick's grade (GET /picks `grade`, from the setup's adjusted edge over the average stock). */
export const GRADES = {
  A: { label: 'A · Proven', kind: 'proven' },
  B: { label: 'B · Promising', kind: 'neutral' },
  C: { label: 'C · Unproven', kind: 'unproven' },
};

/** Engine ideas, then picks by grade; a pick with no or an unknown grade counts as C (no edge so far). */
export const groupByGrade = (items) => ({
  engine: items.filter((i) => i.kind !== 'p'),
  A: items.filter((i) => i.kind === 'p' && i.grade === 'A'),
  B: items.filter((i) => i.kind === 'p' && i.grade === 'B'),
  C: items.filter((i) => i.kind === 'p' && i.grade !== 'A' && i.grade !== 'B'),
});

/** Copy for the New ideas card when nothing is served. */
export const noPickText = (hiddenReason) => ({
  title: 'No picks right now',
  body: hiddenReason ? `${hiddenReason}. Past ones are in History.` : 'No setup has fired on a stock still before its due date. Past ones are in History.',
});

export const ideaFromPick = (p, setup, gradeText = null) => {
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
    // Levels (GET /picks `levels`, backend/forecast/picks.py::levels): target = p90, stop = the tighter of p10 and
    // 3 ATR below entry. A protective plan: the pick is meant to be held to its due date.
    entry: p.entry_ref, stop: p.levels?.stop ?? null, target: p.levels?.target ?? null, qty: null, notional: null, risk: null,
    entryZone: p.levels?.entry_zone ?? null, rewardRisk: p.levels?.reward_risk ?? null,
    toStop: p.levels?.stop != null && p.entry_ref ? p.levels.stop / p.entry_ref - 1 : null,
    reasons: [], thesis: null, why: p.explanation || null,
    range: p.expected ? { p10: p.expected.p10, median: p.expected.median, p90: p.expected.p90 } : null,
    excessRange: ex ? { p10: ex.p10, median: ex.median, p90: ex.p90 } : null,
    forecast: p.forecast || null, similarN: p.similar_n ?? null, features: describeFeatures(p.features),
    pUp: p.p_up, pBeat: p.p_beat_nifty, pastN: p.n,
    oosExcess: setup?.walk_forward?.oos_excess ?? null, oosN: setup?.walk_forward?.oos_n ?? null,
    adjExcess: setup?.adjusted?.excess ?? null, adjT: setup?.adjusted?.t ?? null,
    // The setup held as a monthly basket, out of sample (backend/forecast/study.py::basket).
    basket: setup?.basket?.months ? setup.basket : null,
    grade: p.grade ?? null, gradeText: gradeText?.[p.grade] ?? null,
    missedEntry: p.missed_entry === true, beatsOdds: p.beats_nifty_odds ?? null,
    backfilled: p.backfilled === true, // recomputed after the fact (picks.py::backfill), never in the forward record
    noEdge: p.edge === false, decided: false, experimental: p.experimental === true,
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

/** Ideas → Holdings bands: news is "watch", dated or tax rows "soon", everything else (exits, verdicts, adds,
 * trims, reviews) "act". */
const BAND = { bad_news: 'watch', results_soon: 'soon', ex_dividend: 'soon', ltcg_soon: 'soon', harvest: 'soon' };
const EVENT = { results_soon: 'Results', ex_dividend: 'Ex-dividend' };

/** The holdings rows as three bands. `act` and `watch`: one entry per stock, `{ symbol, items }` in the API's rank
 * order; a stock with anything to act on goes to `act` and takes its news along. `soon`: one entry per row,
 * `{ item, date, label }`, soonest first (the date is the id's last part for results and ex-dividend rows,
 * `backend/mine/actions.py::_action`); undated tax rows last. Pure. */
export const triageHoldings = (actions) => {
  const stocks = new Map();
  const soon = [];
  for (const a of holdingActions(actions)) {
    if (BAND[a.kind] === 'soon') {
      const date = EVENT[a.kind] ? String(a.id).split(':').pop() : null;
      soon.push({ item: a, date: /^\d{4}-\d{2}-\d{2}$/.test(date || '') ? date : null, label: EVENT[a.kind] || null });
      continue;
    }
    const key = a.symbol || a.id;
    if (!stocks.has(key)) stocks.set(key, { symbol: a.symbol, items: [] });
    stocks.get(key).items.push(a);
  }
  const all = [...stocks.values()];
  soon.sort((x, y) => (x.date || '9999').localeCompare(y.date || '9999'));
  return {
    act: all.filter((s) => s.items.some((a) => BAND[a.kind] !== 'watch')),
    watch: all.filter((s) => s.items.every((a) => BAND[a.kind] === 'watch')),
    soon,
  };
};

/** A row's own words without its symbol, which the card already shows: "JINDALSAW: HOLD → SELL" -> "Verdict HOLD →
 * SELL", "SUZLON: Suzlon crashes…" -> "Suzlon crashes…", "Add 9 ADANIPORTS" -> "ADD verdict: 9 more to your target
 * weight". `sub` drops the news rows' boilerplate detail. Pure. */
export const signalText = (a) => {
  const sym = a.symbol || '';
  const t = sym && a.title?.startsWith(`${sym}: `) ? a.title.slice(sym.length + 2) : a.title || '';
  if (a.kind === 'verdict_worse') return { text: `Verdict ${t}`, sub: a.detail || null };
  if (a.kind === 'add' && a.action?.quantity) return { text: `ADD verdict: ${a.action.quantity} more to your target weight`, sub: null };
  return { text: t, sub: a.kind === 'bad_news' ? null : a.detail || null };
};

/** "2026-11-07" -> { dow: 'Fri', day: '7', month: 'Nov' } for the Coming up date block (date-only, no zone shift). */
export const eventDay = (iso) => {
  const d = new Date(`${iso}T00:00:00Z`);
  const f = (o) => d.toLocaleDateString('en-IN', { ...o, timeZone: 'UTC' });
  return { dow: f({ weekday: 'short' }), day: f({ day: 'numeric' }), month: f({ month: 'short' }) };
};

/** Holdings rows that ask for a decision (exits, verdicts, reviews, adds), not the FYI bands (news, dated events, tax). */
export const actNowCount = (actions) => holdingActions(actions).filter((a) => !BAND[a.kind]).length;

/** The ONE "needs you" number: act-now holdings rows plus pending ideas (your suggestions, and today's Picks for
 * admins). News, results, dividends and tax dates are FYI and never inflate it. */
export const needCount = (actions, ideas) =>
  actNowCount(actions) + (Array.isArray(ideas) ? ideas.length : 0);

const HOLDING_DISMISS = {
  stop_hit: 'Keep holding', target_hit: 'Keep holding', idea_exit: 'Keep holding', add: 'Not now',
  verdict_worse: 'Got it', overweight: 'Got it', results_soon: 'Got it', ex_dividend: 'Got it', bad_news: 'Got it', review_due: 'Got it',
};
const HOLDING_LINK = { overweight: 'Trim…', review_due: 'Review thesis', verdict_worse: 'Open stock' };

/** A "Your holdings" row's buttons, named for what the row is about: `primary` (a ticket, an in-app link or
 * an article, or none), then the snooze label (`later`) and the dismiss label. The calls behind them never change. */
export const holdingButtons = (item) => {
  const a = item?.action || {};
  const kind = item?.kind;
  let primary = null;
  if (a.type === 'ticket') {
    primary = { label: a.side === 'BUY' ? 'Buy' : 'Sell', ticket: true };
  } else if (kind === 'bad_news' && a.url) {
    primary = { label: 'Read news', href: a.url };
  } else if (HOLDING_LINK[kind]) {
    primary = { label: HOLDING_LINK[kind], link: true };
  }
  const exit = a.type === 'ticket' && a.side === 'SELL';
  return {
    primary,
    later: kind === 'results_soon' || kind === 'ex_dividend' ? 'Remind me later' : 'Later',
    dismiss: exit ? 'Keep holding' : HOLDING_DISMISS[kind] || 'Dismiss',
  };
};
