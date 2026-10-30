import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sectionOf } from './tabs.js';

test('sectionOf: the active tab, else home', () => {
  assert.equal(sectionOf('/'), 'home');
  assert.equal(sectionOf('/money'), 'money');
  assert.equal(sectionOf('/ideas/abc'), 'ideas');
  assert.equal(sectionOf('/ai/trade/1'), 'ai');
  assert.equal(sectionOf('/news/42'), 'market');
  assert.equal(sectionOf('/stock/INFY'), 'home');
});
