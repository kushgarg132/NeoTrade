import { test } from 'node:test';
import assert from 'node:assert/strict';
import { confidence, ideaFromSuggestion, ideaFromPick, rangeBar, parseIdeaId, describeFeatures, dueLabel, whenLabel, rupeeMove } from './ideas.js';

const sug = { id: 'a1', symbol: 'TCS', side: 'BUY', quantity: 10, entry_ref: 100, stop: 95, target: 110, notional: 1000,
  strategy: 'macd_crossover', reason_codes: ['macd_crossover'], max_hold_days: 5, status: 'PENDING' };
const pick = { _id: '2026-10-19:mom:INFY', symbol: 'INFY', label: 'Momentum', setup: 'mom', horizon: 10, entry_ref: 1500,
  expected: { p10: -0.04, median: 0.02, p90: 0.08 }, p_up: 0.6, p_beat_nifty: 0.55, n: 120, explanation: 'x', edge: true };

test('suggestion view model', () => {
  const v = ideaFromSuggestion(sug);
  assert.equal(v.id, 's-a1');
  assert.equal(v.risk, 50);
  assert.equal(v.headline.value, 0.1);
  assert.equal(v.reasons[0], 'MACD crossover');
});
test('pick view model', () => {
  const v = ideaFromPick(pick, { walk_forward: { oos_excess: 0.01, oos_n: 40 } });
  assert.equal(v.id, 'p-2026-10-19:mom:INFY');
  assert.equal(v.headline.value, 0.02);
  assert.equal(v.oosN, 40);
  assert.equal(v.qty, null);
});
test('parse id splits on the first dash only', () => {
  assert.deepEqual(parseIdeaId('p-2026-10-19:mom:INFY'), { kind: 'p', key: '2026-10-19:mom:INFY' });
  assert.equal(parseIdeaId('zzz'), null);
});
test('rangeBar keeps order and the zero line', () => {
  const r = rangeBar(-0.04, 0.02, 0.08);
  assert.ok(r.p10 === 0 && r.p90 === 100 && r.p10 < r.zero && r.zero < r.median && r.median < r.p90);
  assert.deepEqual(rangeBar(0, 0, 0), { p10: 50, median: 50, p90: 50, zero: 50 });
});

test('confidence splits the composite into rule and AI parts', () => {
  const c = confidence({ rule: 0.6, ai: 0.5, final: 0.68 });
  assert.equal(c.final, 0.68);
  assert.ok(Math.abs(c.ai - 0.08) < 1e-9);
  assert.equal(confidence(null), null);
  assert.equal(ideaFromSuggestion({ ...sug, score: { rule: 0.6, ai: 0.5, final: 0.68 } }).score.rule, 0.6);
});

import { needCount, groupHoldingActions } from './ideas.js';

test('needCount: holdings actions (not idea rows) plus pending ideas; bad shapes count 0', () => {
  const acts = [{ kind: 'bad_news' }, { kind: 'results_soon' }, { kind: 'idea' }, { kind: 'stop_hit' }];
  assert.equal(needCount(acts, [{}, {}]), 5);
  assert.equal(needCount(null, undefined), 0);
});

test('groupHoldingActions groups exits under one title, in order', () => {
  const g = groupHoldingActions([{ kind: 'stop_hit' }, { kind: 'bad_news' }, { kind: 'target_hit' }, { kind: 'idea' }]);
  assert.deepEqual(g.map((x) => [x.title, x.items.length]), [['Exit alerts', 2], ['Bad news', 1]]);
});
test('pick with per-stock forecast keeps excess and describes features', () => {
  const v = ideaFromPick({ ...pick, forecast: 'similar', similar_n: 150, expected: { ...pick.expected, excess: { p10: -0.05, median: 0.015, p90: 0.07 } },
    features: { dist_high: -0.01, vol60: 0.01, mom: 0.2, rel20: 0.05, strength: 1, regime: 1 } });
  assert.equal(v.exMedian, 0.015);
  assert.equal(v.headline.value, 0.02);
  assert.equal(v.similarN, 150);
  assert.equal(v.features[0], 'near its 52-week high');
  assert.ok(v.features.includes('calmer than usual'));
  assert.deepEqual(ideaFromPick(pick).features, []);
});
test('describeFeatures reads regime as a fraction and skips setup-scaled strength', () => {
  const words = describeFeatures({ regime: 0.03, strength: 9 });
  assert.deepEqual(words, ['market in an uptrend']);
  assert.deepEqual(describeFeatures({ regime: 0.01 }), ['market sideways']);
  assert.deepEqual(describeFeatures({ regime: -0.05 }), ['market in a downtrend']);
});

test('pick expected-return fields', () => {
  const v = ideaFromPick({ ...pick, due_date: '2026-11-20', entry_ref: 522.9, expected: { median: 0.011, p10: -0.098, p90: 0.132, excess: { median: -0.0004 }, range_stock: { p10: -0.2, p90: 0.3 } } });
  assert.deepEqual(v.headline, { label: 'in 10 trading days · by 20 Nov', value: 0.011 });
  assert.deepEqual(v.spread, { p10: -0.2, p90: 0.3 });
  assert.equal(v.rupees, '≈ +₹5.8 on ₹522.9');
  assert.deepEqual(ideaFromPick(pick).spread, { p10: -0.04, p90: 0.08 });
});
test('date and rupee helpers', () => {
  assert.equal(dueLabel('2026-11-03'), '3 Nov');
  assert.equal(dueLabel(null), null);
  assert.equal(whenLabel(1, null), 'in 1 trading day');
  assert.equal(rupeeMove(100, -0.05), '≈ −₹5.0 on ₹100.0');
  assert.equal(rupeeMove(null, 0.1), null);
});
