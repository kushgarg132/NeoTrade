import { test } from 'node:test';
import assert from 'node:assert/strict';
import { deliver, shareName, shareRows } from './shareCard.js';

test('shareRows: return, NIFTY and the gap, in percentages only', () => {
  const rows = shareRows({ ret: 0.0123, nifty: 0.004, excess: 0.0083 });
  assert.deepEqual(rows.map((r) => [r.label, r.value, r.tone]), [
    ['My week', '+1.2%', 'gain'], ['NIFTY', '+0.4%', 'gain'], ['Ahead of NIFTY by', '0.8%', 'gain'],
  ]);
  assert.ok(!JSON.stringify(rows).includes('₹'));
});

test('shareRows: a losing week says behind, and a week without a return has no card', () => {
  const rows = shareRows({ ret: -0.02, nifty: 0.01, excess: -0.03 });
  assert.equal(rows[0].value, '-2.0%');
  assert.deepEqual([rows[2].label, rows[2].value, rows[2].tone], ['Behind NIFTY by', '3.0%', 'loss']);
  assert.equal(shareRows({ ret: null }), null);
  assert.equal(shareRows(null), null);
  assert.equal(shareRows({ ret: 0.01 }).length, 1);
});

test('shareName carries the week', () => assert.equal(shareName('2026-W44'), 'neotrade-2026-W44.png'));

test('deliver: share sheet, download fallback, cancel is quiet, other errors surface', async () => {
  const file = { name: 'a.png' };
  const saved = [];
  const save = (f) => saved.push(f);
  assert.equal(await deliver(file, { canShare: () => true, share: async () => {} }, save), 'shared');
  assert.equal(await deliver(file, { canShare: () => false }, save), 'saved');
  assert.equal(await deliver(file, {}, save), 'saved');
  assert.deepEqual(saved, [file, file]);
  const refuse = (name) => ({ canShare: () => true, share: async () => { throw Object.assign(new Error('x'), { name }); } });
  assert.equal(await deliver(file, refuse('AbortError'), save), 'cancelled');
  await assert.rejects(deliver(file, refuse('NotAllowedError'), save));
});
