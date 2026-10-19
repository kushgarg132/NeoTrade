import { test } from 'node:test';
import assert from 'node:assert/strict';
import { visibleSections, barColumns } from './nav.js';

test('non-admins see four tabs, admins six', () => {
  const s = [{ path: '/' }, { path: '/picks', admin: true }, { path: '/ai' }, { path: '/portfolio' }, { path: '/journal' }, { path: '/lab', admin: true }];
  assert.deepEqual(visibleSections(s, false).map((x) => x.path), ['/', '/ai', '/portfolio', '/journal']);
  assert.equal(visibleSections(s, true).length, 6);
});

test('bar columns follow the count', () => {
  assert.equal(barColumns(4), 'grid-cols-4');
  assert.equal(barColumns(6), 'grid-cols-6');
});
