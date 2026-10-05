import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ticketFrom } from './ticket.js';

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
