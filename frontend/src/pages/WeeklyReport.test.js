import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('./WeeklyReport.jsx', import.meta.url), 'utf8');

test('AI book is labelled Paper; your figures say your account', () => {
  assert.match(page, /AI book[\s\S]{0,200}paper|kind="paper"[\s\S]{0,200}AI book/i);
  assert.match(page, /your account/i);
});

test('best and worst are separate labelled groups with dense rows', () => {
  assert.match(page, /Best/);
  assert.match(page, /Worst/);
  assert.match(page, /<ListRow[\s\S]*dense/);
});

test('empty sections name an action; error names the week', () => {
  assert.ok((page.match(/<Empty[\s\S]*?action=/g) || []).length >= 2);
  assert.match(page, /Couldn.t load this week/);
});

test('ideas carry a plain gloss for excess', () => {
  assert.match(page, /better or worse than NIFTY|vs NIFTY/);
  assert.match(page, /after charges/i);
});
