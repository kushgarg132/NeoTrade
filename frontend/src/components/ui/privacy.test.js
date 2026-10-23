import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner here: pin the hide-amounts rule. It once matched only .figure-* nested inside .private,
// so `private figure-md` on one element (every Tile, Stat, ListRow) was never blurred.
const css = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
const rule = css.slice(css.indexOf('html[data-private="on"]'), css.indexOf('{', css.indexOf('html[data-private="on"]')));

test('hide amounts blurs a figure that is itself .private, and a bare .private amount line', () => {
  assert.match(rule, /\.private\.figure-md/);
  assert.match(rule, /\.private\.figure-lg/);
  assert.match(rule, /\.private:not\(:has\(\.figure-md, \.figure-lg, \.private\)\)/);
  assert.match(rule, /\.private \.figure-md/);
});
