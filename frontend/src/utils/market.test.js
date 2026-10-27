import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sectorRows, breadth, divergence, breadthWord, impactWord, sortSectors, materialToday } from './market.js';

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

test('breadthWord thresholds', () => {
  assert.equal(breadthWord({ up: 70, n: 100 }), 'Broad rally');
  assert.equal(breadthWord({ up: 69, n: 100 }), 'Leaning up');
  assert.equal(breadthWord({ up: 55, n: 100 }), 'Leaning up');
  assert.equal(breadthWord({ up: 54, n: 100 }), 'Mixed');
  assert.equal(breadthWord({ up: 46, n: 100 }), 'Mixed');
  assert.equal(breadthWord({ up: 45, n: 100 }), 'Leaning down');
  assert.equal(breadthWord({ up: 31, n: 100 }), 'Leaning down');
  assert.equal(breadthWord({ up: 30, n: 100 }), 'Broad sell-off');
  assert.equal(breadthWord({ up: 0, n: 0 }), '');
});

test('impactWord', () => {
  assert.equal(impactWord(7), 'High');
  assert.equal(impactWord(4), 'Med');
  assert.equal(impactWord(3.9), 'Low');
});

test('sortSectors by each key, null sentiment last, no mutation', () => {
  const rows = [
    { sector: 'a', change_pct: 0.5, sentiment: null, up: 1, n: 10 },
    { sector: 'b', change_pct: -2, sentiment: 0.1, up: 5, n: 10 },
    { sector: 'c', change_pct: 1, sentiment: 0.6, up: 9, n: 10 },
  ];
  const names = (by) => sortSectors(rows, by).map((r) => r.sector).join('');
  assert.equal(names('move'), 'bca');
  assert.equal(names('news'), 'cba');
  assert.equal(names('breadth'), 'cba');
  assert.equal(rows[0].sector, 'a');
});

test('materialToday uses the IST midnight boundary', () => {
  const now = new Date('2026-10-27T06:00:00Z'); // 11:30 IST; IST midnight = 18:30Z prior day
  const items = [
    { id: 1, material: true, published_at: '2026-10-26T18:29:00Z' },
    { id: 2, material: true, published_at: '2026-10-26T18:31:00Z' },
    { id: 3, material: false, published_at: '2026-10-27T05:00:00Z' },
  ];
  const { pinned, rest } = materialToday(items, now);
  assert.deepEqual(pinned.map((i) => i.id), [2]);
  assert.deepEqual(rest.map((i) => i.id), [1, 3]);
});
