import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ticketFrom, executeAll } from './ticket.js';

test('builds a sell ticket from a suggestion', () => {
  assert.deepEqual(ticketFrom({ symbol: 'A', last_price: 10, suggested: { side: 'SELL', quantity: 12, price: 10 } }),
    { symbol: 'A', side: 'SELL', quantity: 12, limitPrice: 10, lastPrice: 10 });
});

test('builds a buy ticket from a rebalance trade', () => {
  assert.deepEqual(ticketFrom({ symbol: 'B', suggested: { side: 'BUY', quantity: 5, price: 370 } }),
    { symbol: 'B', side: 'BUY', quantity: 5, limitPrice: 370, lastPrice: 370 });
});

test('returns null for at-target, skipped or no suggestion', () => {
  assert.equal(ticketFrom({ symbol: 'A', suggested: { at_target: true } }), null);
  assert.equal(ticketFrom({ symbol: 'A', suggested: { skipped: 'charges above 1% of the trade' } }), null);
  assert.equal(ticketFrom({ symbol: 'A', suggested: null }), null);
});

test('rounds the limit to paise', () => {
  assert.equal(ticketFrom({ symbol: 'M', suggested: { side: 'SELL', quantity: 180, price: 224.9199981689453 } }).limitPrice, 224.92);
});

const EP = { orders: { propose: 'P' }, chat: { confirm: (id) => `C:${id}` } };
const fakePost = (fail = {}) => {
  const calls = [];
  const post = async (url, body) => {
    calls.push([url, body]);
    const sym = body.symbol || url.slice(2);
    if (fail[sym] === url[0] + (body.confirm_token ? '2' : '')) throw fail.noAnswer ? new Error('net') : { response: { data: { detail: `no ${sym}` } } };
    if (url === 'P') return { data: { id: body.symbol } };
    return { data: body.confirm_token ? { status: 'CONFIRMED', result: 'ok' } : { status: 'NEEDS_SECOND_TAP', confirm_token: 't' } };
  };
  return { post, calls };
};
const plan = [{ symbol: 'B', side: 'BUY', quantity: 1, price: 10.004 }, { symbol: 'S', side: 'SELL', quantity: 2, price: 20 }];

test('executeAll sells first and redeems the second-tap token for each order', async () => {
  const { post, calls } = fakePost();
  const out = await executeAll(plan, post, EP);
  assert.deepEqual(out.map((o) => [o.symbol, o.status]), [['S', 'done'], ['B', 'done']]);
  assert.deepEqual(calls.map((c) => c[0]), ['P', 'C:S', 'C:S', 'P', 'C:B', 'C:B']);
  assert.equal(calls[3][1].limit_price, 10);
  assert.equal(calls[2][1].confirm_token, 't');
});

test('executeAll stops at the first failure and never buys after a failed sell', async () => {
  const { post, calls } = fakePost({ S: 'C2' });
  const out = await executeAll(plan, post, EP);
  assert.deepEqual(out.map((o) => o.status), ['failed', 'skipped']);
  assert.equal(out[0].note, 'no S');
  assert.ok(!calls.some((c) => c[1].symbol === 'B'));
});

test('executeAll with no answer says the order may be placed', async () => {
  const { post } = fakePost({ S: 'C2', noAnswer: true });
  const out = await executeAll(plan, post, EP);
  assert.equal(out[0].status, 'unknown');
});
