import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Ideas.jsx');
const row = read('../components/ideas/IdeaRow.jsx');
const hold = read('../components/ideas/HoldingActions.jsx');

test('every idea row shows side, entry, stop and R:R without a tap', () => {
  assert.match(row, /idea\.side/);
  assert.match(row, /Entry/);
  assert.match(row, /SL /);
  assert.match(row, /R:R/);
});

test('the list says its figures are a paper record, not advice', () => {
  assert.match(page, /Paper record · not advice/);
  assert.match(page, /kind="paper"/);
});

test('both sections have an Empty that names an action, and the admin gate is kept', () => {
  assert.match(hold, /<Empty[^>]*action=/);
  assert.match(page, /<Empty[^>]*action=/);
  assert.match(page, /role === 'admin'/);
});

test('the holdings alert error names what is affected', () => {
  assert.match(page, /Could not load your holdings alerts\./);
});
