import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { LAB_PAGES } from '../../utils/routes.js';

const lab = readFileSync(new URL('./Lab.jsx', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../App.jsx', import.meta.url), 'utf8');

test('Lab groups and rows', () => {
  for (const g of ['Evidence', 'Tools', 'System']) assert.match(lab, new RegExp(`<Group title="${g}"`));
  const rows = { strategies: 'Strategies', runs: 'Runs', forward: 'Forward', news: 'News accuracy', options: 'Option chain', handbook: 'Handbook', backlog: 'Backlog', beta: 'Beta' };
  for (const [p, t] of Object.entries(rows)) assert.ok(lab.includes(`row('${p}', '${t}'`), p);
  assert.match(lab, /to=\{`\/settings\/lab\/\$\{page\}`\}/);
  assert.doesNotMatch(lab, /<BetaSheet/);
});

test('Beta is a Lab page', () => {
  assert.ok(LAB_PAGES.includes('beta'));
  assert.match(app, /beta: <LabBeta \/>/);
});
