import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ROUTES, ADMIN_ROUTES, MOVED, withSearch, movedTarget, strategyPath, aiTradePath, roundTripPath, indexPath, sectorPath, newsPath } from './routes.js';
import { MAIN_TABS, tabActive } from '../components/layout/tabs.js';
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
  const want = {
    '/portfolio': '/money', '/portfolio/holdings': '/money?tab=holdings', '/portfolio/tax': '/money?tab=tax',
    '/portfolio/import': '/money?tab=holdings', '/portfolio/news': '/market?tab=news',
    '/portfolio/watchlist': '/market?tab=watchlist', '/journal': '/money?tab=journal', '/picks': '/ideas',
    '/ai/book': '/ai?tab=positions', '/ai/activity': '/ai?tab=activity', '/lab': '/settings/lab/strategies',
    '/lab/limits': '/settings/autopilot', '/lab/options': '/settings/lab/options', '/lab/runs': '/settings/lab/runs',
    '/lab/forward': '/settings/lab/forward', '/lab/handbook': '/settings/lab/handbook', '/lab/backlog': '/settings/lab/backlog',
    '/mine': '/money', '/system': '/settings/lab/handbook', '/research': '/',
  };
  for (const [from, to] of Object.entries(want)) assert.equal(m[from], to, from);
});

test('the lab pages are admin routes', () => {
  for (const p of ['strategies', 'options', 'runs', 'forward', 'handbook', 'backlog']) assert.ok(ADMIN_ROUTES.includes(`/settings/lab/${p}`));
  assert.ok(!ADMIN_ROUTES.includes('/settings'));
});

test('old journal tabs become jtab, other query kept', () => {
  assert.equal(movedTarget('/journal', '/money?tab=journal', '?tab=habits'), '/money?tab=journal&jtab=habits');
  assert.equal(movedTarget('/journal', '/money?tab=journal', '?tab=guardrails&x=1'), '/money?tab=journal&x=1&jtab=guardrails');
  assert.equal(movedTarget('/journal', '/money?tab=journal', '?tab=patterns'), '/money?tab=journal&jtab=habits');
  assert.equal(movedTarget('/portfolio', '/money', '?a=1'), '/money?a=1');
});

test('stockPath encodes', () => {
  assert.equal(stockPath('M&M'), '/stock/M%26M');
  assert.equal(stockPath('BAJAJ-AUTO.NS'), '/stock/BAJAJ-AUTO');
});

test('withSearch merges queries instead of doubling the ?', () => {
  assert.equal(withSearch('/journal', ''), '/journal');
  assert.equal(withSearch('/portfolio', '?a=1'), '/portfolio?a=1');
  assert.equal(withSearch('/journal?tab=habits', '?x=1'), '/journal?tab=habits&x=1');
  assert.equal(withSearch('/journal?tab=habits', '?tab=rules'), '/journal?tab=rules');
});


import { brokerReturnTarget } from './routes.js';
test('a broker login redirect anywhere in the app is sent to Settings > Brokers with its code', () => {
  assert.equal(brokerReturnTarget('/', '?code=abc&state=x'), '/settings/brokers?code=abc&state=x');
  assert.equal(brokerReturnTarget('/money', '?request_token=t&action=login&status=success'),
    '/settings/brokers?request_token=t&action=login&status=success');
  assert.equal(brokerReturnTarget('/', '?request_token=y'), '/settings/brokers?request_token=y');
  assert.equal(brokerReturnTarget('/settings/brokers', '?code=x'), null); // already there
  assert.equal(brokerReturnTarget('/money', '?tab=holdings'), null);
});

test('detail builders encode every segment and match a real route', () => {
  assert.equal(strategyPath('picks:pullback'), '/ai/strategy/picks%3Apullback');
  assert.equal(aiTradePath('a/b'), '/ai/trade/a%2Fb');
  assert.equal(newsPath('n 1'), '/news/n%201');
  assert.equal(indexPath('^NSEI'), '/market/index/%5ENSEI');
  assert.equal(sectorPath('Oil & Gas'), '/market/sector/Oil%20%26%20Gas');
  assert.equal(roundTripPath('u1:kite:123'), '/money/trade/u1%3Akite%3A123');
  for (const p of ['/ai/strategy/:name', '/ai/trade/:id', '/money/trade/:id', '/market/index/:ticker', '/market/sector/:name', '/news/:id'])
    assert.ok(ROUTES.includes(p), p);
});

test('the Market tab stays lit on a news item', () => {
  const market = MAIN_TABS.find((t) => t.path === '/market');
  assert.ok(tabActive(market, '/news/abc'));
  assert.ok(!tabActive(MAIN_TABS[0], '/news/abc'));
});
