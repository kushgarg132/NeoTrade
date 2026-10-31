import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const f = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const layout = f('../Layout.jsx');
const chat = f('../ChatWidget.jsx');
const chip = f('./NewsChip.jsx');
const files = [layout, chat, chip, f('./StopAutopilot.jsx')];

test('shared chrome: no doc-meta, shadow- or sheet classes', () => {
  for (const s of files) {
    assert.doesNotMatch(s, /doc-meta/);
    assert.doesNotMatch(s, /shadow-/);
    assert.doesNotMatch(s, /["' ]sheet[ "']/);
  }
});

test('layout toast is a plain bordered card', () => {
  assert.match(layout, /rounded-\[12px\]/);
  assert.match(layout, /border-\[var\(--border\)\]/);
});

test('chat launcher keeps its border; truncation survives', () => {
  assert.match(chat, /border border-\[var\(--border\)\]/);
  assert.match(chat, /truncate/);
  assert.match(chip, /truncate/);
});

test('chat lives once in App (signed-in only), not per page, and cancels its stream on unmount', () => {
  const app = f('../../App.jsx');
  assert.doesNotMatch(layout, /ChatWidget/);
  assert.match(app, /\{user && <ChatWidget \/>\}/);
  assert.equal((app.match(/<ChatWidget/g) || []).length, 1);
  assert.match(chat, /requestRef\.current\?\.cancel\(\)/);
});

test('AiTrade reads only the snapshot: useStockAnalysis can skip the AI read', () => {
  assert.match(f('../stock/useStockAnalysis.js'), /\{ ai: wantAi = true \}/);
  assert.match(f('../stock/useStockAnalysis.js'), /!symbol \|\| !wantAi/);
  assert.match(f('../../pages/AiTrade.jsx'), /useStockAnalysis\(t\?\.symbol, \{ ai: false \}\)/);
});

test('per-share prices keep their paise (px); totals stay on inr', () => {
  for (const [file, re] of [
    ['../../pages/RoundTrip.jsx', /px\(entry\)[\s\S]*px\(exit\)[\s\S]*px\(f\.price\)/],
    ['../../pages/Stock.jsx', /px\(pos\.avg\)[\s\S]*px\(risk\.stop\)[\s\S]*px\(risk\.target\)/],
    ['../../pages/AiTrade.jsx', /px\(c\.stop\)[\s\S]*px\(c\.target\)[\s\S]*px\(t\.entry_price\)[\s\S]*px\(t\.exit_price\)/],
    ['../ai/Positions.jsx', /px\(p\.avg_price\)/],
  ]) assert.match(f(file), re, file);
});

test('useLoad keys its result by loader; weekly arrows shift from the URL week', () => {
  const load = f('../ideas/useLoad.js');
  assert.match(load, /raw\.fn === fn \? raw :/);
  assert.match(load, /setS\(\{ fn, data/);
  assert.match(f('../../pages/WeeklyReport.jsx'), /shiftWeek\(week \|\| r\?\.week, by\)/);
});

test('SmartSearch drops an older query reply', () => {
  const s = f('../dashboard/SmartSearch.jsx');
  assert.match(s, /if \(!live\) return;/);
  assert.match(s, /live = false; clearTimeout\(handle\)/);
});

test('Rebalance money is hide-amounts private', () => {
  const s = f('../portfolio/Rebalance.jsx');
  for (const re of [/className="private" label="Total cost"/, /className="private" label="Value"/, /mono className="private">\{formatCurrency\(t\.value\)/,
    /cash left <span className="private">/, /figure-md text-sm private/]) assert.match(s, re);
});

test('AI money in ListRow sub lines is wrapped in private spans', () => {
  assert.match(f('../ai/Scoreboard.jsx'), /const amount = \(n\) => <span className="private">/);
  assert.doesNotMatch(f('../ai/Scoreboard.jsx'), /`\$\{st\.trades\} closed/);
  assert.match(f('../ai/Positions.jsx'), /<span className="private">\{px\(p\.avg_price\)\}/);
});

test('/auth/me clears the token only on a 401 and retries other failures once', () => {
  const s = f('../../context/AuthContext.jsx');
  assert.match(s, /err\?\.response\?\.status === 401/);
  assert.match(s, /attempt < 2/);
  assert.doesNotMatch(s, /\} catch \{\s*if \(!cancelled\) \{\s*localStorage\.removeItem/);
});

test('Money total P&L percent shows a dash when pnl_pct is missing', () => {
  assert.match(f('../../pages/Money.jsx'), /h\.pnl_pct != null \? pct\(h\.pnl_pct \/ 100, \{ sign: true \}\) : '—'/);
});

test('Scorecard drops stale replies; Watchlist rollback restores only the failed row', () => {
  const sc = f('../paper/Scorecard.jsx');
  assert.match(sc, /mine !== latest\.current/);
  const wl = f('../market/Watchlist.jsx');
  assert.doesNotMatch(wl, /setRows\(previous\)/);
  assert.match(wl, /\[\.\.\.list\.slice\(0, at\), gone, \.\.\.list\.slice\(at\)\]/);
});

test('opening a stock loads the stored AI read only; a run needs the Generate or Refresh button', () => {
  const hook = f('../stock/useStockAnalysis.js');
  assert.match(hook, /if \(!aiTry\) \{ \/\/ on open: the stored read only/);
  assert.match(hook, /api\.get\(endpoints\.stockNote\(symbol\)\)/);
  assert.match(hook, /aiRun\.symbol === symbol \? aiRun\.n : 0/); // another stock's run count never carries over
  const card = f('../stock/AiRead.jsx');
  assert.match(card, />Generate</);
  assert.match(card, /read && stale && !busy && !error/);
});

test('a tab switch (a REPLACE on the same path) keeps the scroll; a new path opens at the top', () => {
  const app = f('../../App.jsx');
  assert.match(app, /if \(scrolledPath\.current === pathname\) return;/);
  assert.match(app, /if \(navigationType !== 'POP'\) window\.scrollTo\(0, 0\);/);
});

test('AiRead shows a stored read: it says summary/sentiment_analysis, a fresh report analyst_summary/sentiment', () => {
  const card = f('../stock/AiRead.jsx');
  assert.match(card, /read\?\.analyst_summary \?\? read\?\.summary/);
  assert.match(card, /read\?\.sentiment \?\? read\?\.sentiment_analysis/);
});
