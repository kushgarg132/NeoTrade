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
