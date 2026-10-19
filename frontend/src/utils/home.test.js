import test from 'node:test';
import assert from 'node:assert/strict';
import { tileHeadlines, briefKind, showWeekly, alerts } from './home.js';

test('missing data gives dashes, never throws', () => {
  const t = tileHeadlines(null, null, null);
  assert.equal(t.money.value, '—');
  assert.equal(t.ideas.value, '—');
  assert.equal(t.ai.value, '—');
  assert.equal(t.market.value, '—');
});

test('full data', () => {
  const t = tileHeadlines(
    { proposals_total: 3, mine_actions: [{ kind: 'stop_hit' }, { kind: 'idea' }],
      scoreboard: { today: { ai: 1200, mine: 0 }, month: { ai: 5000, mine: -300 } },
      backdrop: { regime: { label: 'risk_on' } } },
    { headline: { value: 409205, day_change: 3000, day_change_pct: 0.74, xirr: 0.142 } },
    [{ name: 'NIFTY 50', percent: -0.4 }],
  );
  assert.equal(t.money.value, '₹4,09,205');
  assert.equal(t.money.sub, 'today +0.74%');
  assert.equal(t.ideas.sub, '3 proven · 1 exit');
  assert.equal(t.ai.value, '+₹1,200');
  assert.equal(t.market.value, '-0.40%');
  assert.equal(t.market.tone, 'loss');
});

test('partial: pulse without overview, regime without index', () => {
  const t = tileHeadlines({ pulse: { value: 1000, day_change: 0, day_change_pct: 0 }, backdrop: { regime: { label: 'neutral' } } }, null, []);
  assert.equal(t.money.sub, 'today 0.00%');
  assert.equal(t.market.value, 'Neutral');
});

test('brief kind and weekly day', () => {
  assert.equal(briefKind('pre'), 'premarket');
  assert.equal(briefKind('post'), 'postclose');
  assert.equal(briefKind('session'), null);
  assert.equal(showWeekly(new Date('2026-10-18T06:00:00Z')), true); // Sunday
  assert.equal(showWeekly(new Date('2026-10-21T06:00:00Z')), false);
});

test('alerts only when something needs attention', () => {
  assert.deepEqual(alerts(null), []);
  assert.deepEqual(alerts({ accounts: { mine: { broker: 'kite', state: 'ACTIVE' } }, live_armed: { autopilot: false, strategies: [] }, kill_switch: { tripped: false } }), []);
  const a = alerts({ accounts: { mine: { broker: 'kite', state: 'EXPIRED' } }, live_armed: { autopilot: true, strategies: ['x'] }, kill_switch: { tripped: true } });
  assert.deepEqual(a.map((x) => x.id), ['login-mine', 'kill', 'live']);
  assert.equal(a[2].to, '/ai');
});
