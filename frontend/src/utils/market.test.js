import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sectorRows, breadth, divergence } from './market.js';

test('divergence flags news and price disagreeing, only for strong news', () => {
  assert.equal(divergence({ sentiment: 0.4, change_pct: -1.2 }), 'good news, falling');
  assert.equal(divergence({ sentiment: -0.3, change_pct: 0.5 }), 'bad news, rising');
  assert.equal(divergence({ sentiment: 0.29, change_pct: -1 }), null); // weak news
  assert.equal(divergence({ sentiment: 0.6, change_pct: 1 }), null); // agree
  assert.equal(divergence({ sentiment: -0.6, change_pct: 0 }), null); // flat
  assert.equal(divergence({ sentiment: null, change_pct: -2 }), null); // no news
  assert.equal(divergence(), null);
});

const item = (...impacts) => ({ impacts });
test('sectorRows nets signed impact per sector, strongest first', () => {
  const rows = sectorRows([
    item({ type: 'sector', target: 'IT', direction: 1, impact: 6 }, { type: 'market', target: 'x', direction: 1, impact: 9 }),
    item({ type: 'sector', target: 'IT', direction: 1, impact: 2 }, { type: 'sector', target: 'Banks', direction: -1, impact: 9 }),
    item({ type: 'sector', target: 'Auto', direction: 0, impact: 5 }),
  ]);
  assert.deepEqual(rows.map((r) => [r.sector, r.score, r.count]), [['Banks', -9, 1], ['IT', 8, 2]]);
  assert.deepEqual(sectorRows(undefined), []);
});

test('breadth counts advancers and decliners', () => {
  assert.deepEqual(breadth([{ percent: 1 }, { percent: -2 }, { percent: 0 }, {}]), { up: 1, down: 1 });
});
