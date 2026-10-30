import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// No DOM runner here: pin the hide-amounts rule. It once matched only .figure-* nested inside .private,
// so `private figure-md` on one element (every Tile, Stat, ListRow) was never hidden.
const css = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
const rule = css.slice(css.indexOf('html[data-private="on"]'), css.indexOf('{', css.indexOf('html[data-private="on"]')));

test('hide amounts masks a figure that is itself .private, and a bare .private amount line', () => {
  assert.match(rule, /\.private\.figure-md/);
  assert.match(rule, /\.private\.figure-lg/);
  assert.match(rule, /\.private:not\(:has\(\.figure-md, \.figure-lg, \.private\)\)/);
  assert.match(rule, /\.private \.figure-md/);
});

test('hide amounts masks with dots, not a blur', () => {
  const body = css.slice(css.indexOf('{', css.indexOf('html[data-private="on"]')));
  assert.match(body.slice(0, 400), /content: '••••'/);
  assert.doesNotMatch(body.slice(0, 400), /blur/);
});
