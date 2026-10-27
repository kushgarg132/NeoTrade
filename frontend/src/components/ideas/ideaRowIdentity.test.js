import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract tests: no DOM runner here.
const rd = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const row = rd('./IdeaRow.jsx');
const rec = rd('../suggestions/SuggestionRecord.jsx');

test('a graded pick shows a GradeTile; an unknown grade shows none', () => {
  assert.match(row, /import GradeTile from '..\/ui\/GradeTile'/);
  assert.match(row, /GRADES\[idea\.grade\] && <span className="shrink-0"><GradeTile grade=\{idea\.grade\}/);
  assert.doesNotMatch(row, /<Badge kind=\{GRADES\[/);
});

test('tile is the first child of the row link', () => {
  assert.match(row, /<Link [^>]*>\s*\{GRADES\[idea\.grade\] && <span[^>]*><GradeTile[^>]*\/><\/span>\}\s*<div className="min-w-0 flex-1">/);
});

test('soft tokens, no wash', () => {
  assert.doesNotMatch(row, /-wash\)/);
  assert.doesNotMatch(rec, /-wash\)/);
  assert.match(row, /--gain-soft/);
  assert.match(row, /--loss-soft/);
});
