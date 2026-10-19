import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ROUTES, ADMIN_ROUTES, MOVED } from './routes.js';
import { stockPath } from './stocks.js';

test('every redirect lands on a real route in one hop', () => {
  const real = new Set(ROUTES);
  for (const [from, to] of MOVED) {
    assert.ok(real.has(to.split('?')[0]), `${from} -> ${to}`);
    assert.ok(!MOVED.some(([f]) => f === to.split('?')[0]), `${to} is itself moved`);
  }
});

test('old paths map where the spec says', () => {
  const m = Object.fromEntries(MOVED);
  assert.equal(m['/mine'], '/portfolio');
  assert.equal(m['/mine/journal'], '/journal');
  assert.equal(m['/mine/habits'], '/journal?tab=habits');
  assert.equal(m['/research/news'], '/portfolio/news');
  assert.equal(m['/ai/settings'], '/lab/limits');
  assert.equal(m['/system'], '/lab/handbook');
  assert.equal(m['/research'], '/');
  assert.equal(m['/import'], '/portfolio/import');
});

test('picks and lab are admin routes', () => {
  for (const p of ['/picks', '/lab', '/lab/limits', '/lab/options', '/lab/handbook', '/lab/backlog']) assert.ok(ADMIN_ROUTES.includes(p));
});

test('stockPath encodes', () => {
  assert.equal(stockPath('M&M'), '/stock/M%26M');
  assert.equal(stockPath('BAJAJ-AUTO.NS'), '/stock/BAJAJ-AUTO');
});
