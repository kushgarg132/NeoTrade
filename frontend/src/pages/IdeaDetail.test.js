import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('./IdeaDetail.jsx', import.meta.url), 'utf8');
const at = (re) => src.search(re);

test('the top of the page is the trade plan, then the action, then the folds', () => {
  const plan = at(/<Stat label="Entry"/), buy = at(/<BuyBar idea/);
  assert.ok(plan > 0 && buy > plan && at(/<Fold title="Why/) > buy);
  assert.match(src, /R:R/);
  assert.match(src, /Stop/);
});

test('Why, Track record fold into native details', () => {
  assert.match(src, /<details/);
  assert.match(src, /<Fold title="Why/);
  assert.match(src, /<Fold title="Track record/);
});

test('figures carry a paper line and the jargon is glossed', () => {
  assert.match(src, /Paper record · not advice/);
  assert.match(src, /kind="paper"/);
  assert.match(src, /10th to 90th|p10/);
  assert.match(src, /out-of-sample[^\n]*(held back|unseen)|held back/i);
  assert.match(src, /t-score|t \d|"t"/);
});

test('confidence is one line; the second-tap BuyBar and gates are untouched', () => {
  assert.match(src, /Confidence <b>/);
  assert.match(src, /<BuyBar idea=\{idea\} id=\{key\} onDone=\{done\}/);
  assert.match(src, /Empty title="Idea not found"/);
});

test('IdeaRow imports everything it uses', () => {
  const row = readFileSync(new URL('../components/ideas/IdeaRow.jsx', import.meta.url), 'utf8');
  assert.match(row, /import \{ toneText \}/);
});
