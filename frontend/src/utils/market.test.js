import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sectorRows, breadth } from './market.js';

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
