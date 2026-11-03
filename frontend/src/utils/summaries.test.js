import { test } from 'node:test';
import assert from 'node:assert/strict';
import { summaryLines } from './summaries.js';

test('summaryLines drops blanks', () => {
  assert.deepEqual(summaryLines('a\n\n  b \n'), ['a', 'b']);
  assert.deepEqual(summaryLines(undefined), []);
});
