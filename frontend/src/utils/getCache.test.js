import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeGetCache } from './getCache.js';

const counting = () => {
  const calls = [];
  const get = (url) => { calls.push(url); return Promise.resolve({ data: { url, n: calls.length } }); };
  return { calls, get };
};

test('identical GETs share one request and a repeat within the TTL is served from memory', async () => {
  let now = 0;
  const { calls, get } = counting();
  const cache = makeGetCache(get, { ttlMs: 30_000, now: () => now, key: () => 'tok' });
  const [a, b] = await Promise.all([cache.get('/x'), cache.get('/x')]);
  assert.equal(calls.length, 1);
  assert.equal(a, b);
  now = 29_000;
  await cache.get('/x');
  assert.equal(calls.length, 1);
  now = 31_000;
  await cache.get('/x');
  assert.equal(calls.length, 2);
});

test('params, the user token and cache:false keep requests apart', async () => {
  let token = 'a';
  const { calls, get } = counting();
  const cache = makeGetCache(get, { ttlMs: 30_000, now: () => 0, key: () => token });
  await cache.get('/x', { params: { a: 1 } });
  await cache.get('/x', { params: { a: 2 } });
  token = 'b';
  await cache.get('/x', { params: { a: 1 } });
  await cache.get('/x', { params: { a: 1 }, cache: false });
  assert.equal(calls.length, 4);
});

test('clear() drops everything and a failed GET is not cached', async () => {
  let fail = true;
  const calls = [];
  const get = (url) => { calls.push(url); return fail ? Promise.reject(new Error('down')) : Promise.resolve({ data: 1 }); };
  const cache = makeGetCache(get, { ttlMs: 30_000, now: () => 0, key: () => 't' });
  await assert.rejects(cache.get('/x'));
  fail = false;
  await cache.get('/x');
  assert.equal(calls.length, 2);
  cache.clear();
  await cache.get('/x');
  assert.equal(calls.length, 3);
});
