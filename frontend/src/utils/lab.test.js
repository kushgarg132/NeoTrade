import test from 'node:test';
import assert from 'node:assert/strict';
import {
  strategiesState, runsState, forwardState, newsAccuracyState, handbookState, backlogState, betaState,
} from './lab.js';

test('undefined is a dash everywhere', () => {
  for (const f of [strategiesState, runsState, forwardState, newsAccuracyState, handbookState, backlogState, betaState]) {
    assert.equal(f(undefined), '–');
  }
});

test('strategies', () => {
  const strategies = Array.from({ length: 12 }, (_, i) => ({ live_switch: i < 2 }));
  assert.equal(strategiesState({ strategies }), '12 strategies · 2 live');
  assert.equal(strategiesState({ strategies: [] }), 'No strategies');
});

test('runs', () => {
  const now = Date.parse('2026-10-27T11:00:00Z');
  assert.equal(runsState({ runs: [{ created_at: '2026-10-25T10:00:00Z' }] }, now), 'Last run 2d ago');
  assert.equal(runsState({ runs: [{ created_at: '2026-10-27T01:00:00Z' }] }, now), 'Last run today');
  assert.equal(runsState({ runs: [] }, now), 'No runs yet');
});

test('forward', () => {
  assert.equal(forwardState({ rows: [{ n: 400 }, { n: 12 }] }), '412 scored');
  assert.equal(forwardState({ rows: [] }), 'Nothing scored yet');
});

test('news accuracy', () => {
  assert.equal(newsAccuracyState(null), 'No report yet');
  assert.equal(newsAccuracyState({ as_of: '2026-10-27T05:00:00Z' }), 'Built 27 Oct');
  assert.equal(newsAccuracyState({ as_of: '2026-10-27', company_scan_ok: false }), 'Built 27 Oct · company scan off');
});

test('handbook', () => {
  assert.equal(handbookState({ as_of: 'x', a: {}, b: { error: 'E' } }), '1 failing');
  assert.equal(handbookState({ as_of: 'x', a: {} }), 'All checks ok');
});

test('backlog', () => {
  assert.equal(backlogState({ items: [{ status: 'idea' }, { status: 'done' }, { status: 'dropped' }] }), '1 open');
});

test('beta', () => {
  assert.equal(betaState({ returned_from_last_week: 3, active_last_week: 5 }), '3 of 5 came back');
});

test('runsState reads a naive created_at as UTC', () => {
  assert.equal(runsState({ runs: [{ created_at: '2026-10-26T20:00:00' }] }, Date.parse('2026-10-27T19:00:00Z')), 'Last run today');
});
