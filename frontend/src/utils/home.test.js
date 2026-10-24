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
    { backdrop: { regime: { label: 'risk_on' } } },
    { headline: { value: 409205, day_change: 3000, day_change_pct: 0.74, xirr: 0.142 } },
    [{ name: 'NIFTY 50', percent: -0.4 }],
    { count: 4, actions: [{ kind: 'bad_news' }, { kind: 'stop_hit' }, { kind: 'idea' }], ideas: [{}, {}] },
    { value: 1050000, day: 1200, dayPct: 0.0012 },
  );
  assert.equal(t.money.value, '₹4,09,205');
  assert.equal(t.money.sub, 'today +0.74%');
  assert.equal(t.ideas.value, '4');
  assert.equal(t.ideas.sub, '2 to review · 2 ideas');
  assert.equal(t.ai.value, '₹10,50,000');
  assert.equal(t.ai.sub, 'today +₹1,200 (+0.12%)');
  assert.equal(t.market.value, '-0.40%');
  assert.equal(t.market.tone, 'loss');
});

test('partial: pulse without overview, regime without index', () => {
  const t = tileHeadlines({ pulse: { value: 1000, day_change: 0, day_change_pct: 0 }, backdrop: { regime: { label: 'neutral' } } }, null, []);
  assert.equal(t.money.sub, 'today 0.00%');
  assert.equal(t.market.value, 'Neutral');
});

test('a non-array indices response does not crash', () => {
  assert.equal(tileHeadlines({}, null, { error: 'x' }).market.value, '—');
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

test('outside the session the day change is the last session, and tiles carry freshness', () => {
  const now = Date.parse('2026-10-24T06:00:00Z'); // Saturday
  const t = tileHeadlines(
    { phase: 'closed' },
    { headline: { value: 1000, day_change: 10, day_change_pct: 1, as_of: '2026-10-24T05:59:00Z' } },
    [{ name: 'NIFTY 50', percent: 0.5, at: now / 1000 - 600 }],
    null, null, now,
  );
  assert.equal(t.money.sub, 'last session +1.00%');
  assert.equal(t.money.meta.text, 'Market closed · last close');
  assert.equal(t.market.meta.text, 'Market closed · last close');
  assert.equal(tileHeadlines({ phase: 'session' }, null, [{ name: 'NIFTY 50', percent: 0.5 }]).market.meta, null);
});

test('an expired login alert names its broker so the tap can open that broker login', () => {
  const [up, ai] = alerts({ accounts: { mine: { broker: 'upstox', state: 'EXPIRED' }, ai: { broker: 'kite', state: 'EXPIRED' } } });
  assert.equal(up.login, 'upstox');
  assert.equal(ai.login, 'kite');
  assert.equal(up.to, '/settings?tab=accounts'); // the fallback when the login URL cannot be built
});
