// Every `endpoints.a.b` used in src must exist: an undefined path sends the request to the API root
// (the goal form shipped that way on 2026-10-19). Reads the source of api.js, so no browser globals.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

const loadEndpoints = () => {
  const src = readFileSync(join(root, 'utils/api.js'), 'utf8');
  const i = src.indexOf('{', src.indexOf('export const endpoints = {'));
  let depth = 0, j = i;
  for (; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && !--depth) break;
  }
  return Function(`return (${src.slice(i, j + 1)})`)();
};

const sources = (dir, out = []) => {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) sources(p, out);
    else if (/\.(jsx?|mjs)$/.test(f) && !/\.test\./.test(f)) out.push(p);
  }
  return out;
};

test('every endpoints.* reference resolves', () => {
  const endpoints = loadEndpoints();
  const missing = [];
  for (const file of sources(root)) {
    for (const m of readFileSync(file, 'utf8').matchAll(/endpoints((?:\.[A-Za-z_]\w*)+)/g)) {
      const path = m[1].slice(1).split('.');
      if (path.reduce((v, k) => v?.[k], endpoints) === undefined) missing.push(`${file.replace(root, '')}: endpoints.${path.join('.')}`);
    }
  }
  assert.deepEqual(missing, []);
});
