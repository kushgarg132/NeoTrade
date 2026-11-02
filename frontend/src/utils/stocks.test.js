import { test } from 'node:test';
import assert from 'node:assert/strict';
import { logoUrl } from './stocks.js';

test('logoUrl: production reads the cached copy on our server, dev goes to FMP', () => {
  assert.equal(logoUrl('RELIANCE', true), 'https://neotrade.161.118.167.148.nip.io/logo/RELIANCE.png');
  assert.equal(logoUrl('RELIANCE', false), 'https://financialmodelingprep.com/image-stock/RELIANCE.NS.png');
});

test('logoUrl: symbols are encoded, so M&M stays one path segment', () => {
  assert.equal(logoUrl('M&M', true), 'https://neotrade.161.118.167.148.nip.io/logo/M%26M.png');
  assert.equal(logoUrl('M&M', false), 'https://financialmodelingprep.com/image-stock/M%26M.NS.png');
});

test('isDerivative spots F&O contracts, not stocks', async () => {
  const { isDerivative } = await import('./stocks.js');
  assert.equal(isDerivative('NIFTY24OCT25000CE'), true);
  assert.equal(isDerivative('RELIANCE24OCTFUT'), true);
  assert.equal(isDerivative('RELIANCE'), false);
  assert.equal(isDerivative('M&M'), false);
  assert.equal(isDerivative(null), false);
});
