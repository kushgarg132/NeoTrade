import test from 'node:test';
import assert from 'node:assert/strict';
import { safeGet, safeSet } from './storage.js';

test('blocked storage does not throw', () => {
  globalThis.localStorage = {
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('blocked'); },
  };
  assert.equal(safeGet('k'), null);
  assert.doesNotThrow(() => safeSet('k', 'v'));
});

test('works when storage works', () => {
  const m = new Map();
  globalThis.localStorage = { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) };
  safeSet('k', 'v');
  assert.equal(safeGet('k'), 'v');
});
