import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Source-contract tests (no DOM runner): a signed-out visitor on a public page makes no personal call
// and opens no socket; personal blocks become a SignInCard.
const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const home = read('./Home.jsx');
const market = read('./Market.jsx');
const today = read('../components/market/Today.jsx');
const news = read('../components/market/News.jsx');
const stock = read('./Stock.jsx');
const analysis = read('../components/stock/useStockAnalysis.js');
const index = read('./IndexPage.jsx');
const app = read('../App.jsx');

const GUARD = /if \(!user\)|user &&|user \?/;

test('App: a public page waits for the session check, as RequireAuth does', () => {
  const open = app.slice(app.indexOf('const open = '), app.indexOf('const gated = '));
  assert.match(open, /loading/);
  assert.match(app, /const \{ user, loading \} = useAuth\(\)/);
});

test('Home: guests get brief, indices, five news items and one sign-in card', () => {
  assert.match(home, /useAuth\(\)/);
  const guest = home.slice(home.indexOf('const GuestHome = '), home.indexOf('\nconst ', home.indexOf('const GuestHome = ') + 10));
  assert.match(guest, /SignInCard title="Track your money" body="Sign in to connect Zerodha, Upstox or Angel One and see your holdings and P&L\."/);
  assert.match(guest, /endpoints\.marketBrief/);
  assert.match(guest, /endpoints\.marketIndices/);
  assert.match(guest, /endpoints\.newsFeed, \{ params: \{ limit: 5 \} \}/);
  assert.doesNotMatch(guest, /endpoints\.(today|mine|analytics|summaries|broker)\b/);
  assert.doesNotMatch(guest, /useRefetchOn|useTopic|stream\./);
  assert.match(home, /user \? <MemberHome \/> : <GuestHome \/>/);
});

test('Market: Watchlist tab is a sign-in card for guests; Today skips /today; News opens no socket', () => {
  assert.match(market, /useAuth/);
  assert.match(market, /tab === 'watchlist' && \(user \? <Watchlist \/> : <SignInCard title="Your watchlist"/);
  assert.match(today, /useAuth/);
  assert.match(today, /user && <Events \/>/);
  assert.match(news, /useTopic\(user \? 'news' : null/);
  assert.match(news, /useState\(!!user\)/); // "My names" needs an account
});

test('Stock: position, watchlist and overview only when signed in; watch/trade/AI show the card', () => {
  assert.match(stock, /useAuth/);
  assert.match(stock, /import SignInCard from '..\/components\/SignInCard'/);
  for (const ep of ['mine.stock', 'watchlist.list', 'mine.overview']) {
    const at = stock.indexOf(`endpoints.${ep}`);
    assert.ok(at > 0, ep);
    assert.match(stock.slice(Math.max(0, at - 300), at), GUARD, ep);
  }
  assert.match(stock, /title: 'Sign in to watch or trade'/);
  assert.match(analysis, /user \? stream\.request\('quick_analyze'/);
});

test('IndexPage: guests read the cached story only; explain asks to sign in', () => {
  assert.match(index, /useAuth/);
  assert.match(index, /import SignInCard from '..\/components\/SignInCard'/);
  assert.match(index, /const generate = user \? run :/);
});
