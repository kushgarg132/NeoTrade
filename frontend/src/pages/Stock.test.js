import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const page = read('./Stock.jsx');
const gauge = read('../components/stock/TechGauge.jsx');
const analysis = read('../components/stock/DetailsTab.jsx');

test('technical gauge uses chartTheme and the Details tab renders it', () => {
  assert.match(gauge, /from '..\/ui\/chartTheme'/);
  assert.match(gauge, /heatColor\(/);
  assert.match(analysis, /<TechGauge/);
});

const position = read('../components/stock/Position.jsx');
const facts = read('../components/stock/MarketFacts.jsx');

test('position block is a risk view: avg, qty, P&L, XIRR, held since, stop distance, private', () => {
  assert.match(position, /Your position · your broker account/);
  assert.match(position, /risk\.dist/);
  assert.match(position, /if hit/);
  assert.match(position, /held\.xirr/);
  assert.match(position, /held_since/);
  assert.match(position, /className=\{`private /);
  assert.match(page, /<Position symbol=\{symbol\}/);
});

test('lots show days to long-term and the tax a sale would cost; more than two fold', () => {
  assert.match(position, /days_to_long/);
  assert.match(position, /tax if sold/);
  assert.match(position, /LOTS_SHOWN = 2/);
});

test('your plan is set and edited in place through PUT /mine/thesis', () => {
  assert.match(position, /api\.put\(endpoints\.mine\.thesis\(symbol\)/);
  assert.match(position, /Set plan/);
  assert.match(position, /raise alerts/);
});

test('errors say what failed and offer Retry', () => {
  assert.match(position, /Could not load your position from your broker account/);
  assert.match(analysis, /Could not load the price snapshot[^\n]*onRetry=\{reloadQuick\}/);
});

test('a disabled Buy is explained in words', () => {
  assert.match(page, /Buy is off until a price loads/);
});

test('order flow untouched: Buy and Sell still open the ticket', () => {
  assert.match(page, /side: 'SELL'/);
  assert.match(page, /side: 'BUY'/);
});

test('stop-hit loss shows from-now and vs-cost, both private', () => {
  assert.match(position, /\(stop - price\) \* pos\.qty/);
  assert.match(position, /<span className="private">\{inr\(risk\.fromNow[^\n]*from now/);
  assert.match(position, /<span className="private">\(\{inr\(risk\.pnl[^\n]*vs what you paid/);
});

// Hide-amounts blurs a `.private` only when it holds no `.private` descendant, so the stop line must
// not wrap its own private spans, and the chart legend must blur the amounts too.
test('stop and target amounts are their own private spans, with no private wrapper', () => {
  assert.doesNotMatch(position, /<p className="private">\s*Stop/);
  assert.match(position, /Stop <span className="private">\{px\(stop\)\}/);
  assert.match(position, /Target <span className="private font-semibold">\{px\(t\.target\)\}/);
  const chart = readFileSync(new URL('../components/stock/TradingChart.jsx', import.meta.url), 'utf8');
  assert.match(chart, /<span className="private">\{fmt\(l\.price\)\}/);
  assert.match(chart, /<PriceCanvas/);
  assert.match(chart, /hidePrices=\{hidden\}/); // the canvas axis cannot blur, so it hides stop/target prices
});

test('the chart reads OHLCV: Stock.jsx passes candles and mine.bars, never closes', () => {
  assert.match(page, /m\?\.bars/);
  assert.match(page, /toBars\(/);
  assert.doesNotMatch(page, /m\?\.closes/);
});

test('price sits on the Hero, not a Card, and stays public', () => {
  assert.match(page, /<Hero[^>]*privateValue=\{false\}/);
  assert.match(page, /format=\{currency === 'INR' \? px : points\}/); // paise, as the chart readout prints it
  assert.match(page, /<DeltaChip[^>]*value=\{currency === 'INR' \? dayAbs : null\}/);
  assert.match(page, /format=\{inrPaise\}/); // the move to the paise, as the chart prints it
  assert.match(page, /pct=\{dayPct \* 100\}/);
  assert.match(page, /<DeltaChip[\s\S]*?privateValue=\{false\}/);
  assert.match(page, /aria-pressed=\{watching\}/);
  assert.match(page, /<AsOf /);
  assert.match(position, /data-testid="stop-line"/);
  assert.doesNotMatch(page, /text-\[28px\]/);
});

test('the Details tab has no thesis card', () => {
  const details = readFileSync(new URL('../components/stock/DetailsTab.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(details, /ThesisEditor|Your thesis/);
});

test('fundamentals sit under the chart, not in Details', () => {
  assert.match(page, /<TradingChart[\s\S]*?<Fundamentals company=\{company\}/);
  const details = readFileSync(new URL('../components/stock/DetailsTab.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(details, /<Fundamentals/);
});

test('order above the tabs: position (with the verdict), AI read, how it has done; signed out the bar says Sign in to trade', () => {
  const at = (x) => page.indexOf(x);
  assert.ok(at('<Position ') < at('<AiRead aiRead=') && at('<AiRead aiRead=') < at('<MarketFacts ') && at('<MarketFacts ') < at('<Tabs tabs={TABS}'));
  assert.match(page, /!user \? <Button variant="secondary" className="flex-1" onClick=\{\(\) => askSignIn\(WATCH_OR_TRADE\)\}>Sign in to trade<\/Button>/);
});

test('a holding opens its chart on 6M or 1Y (wide enough for the first buy), where its trades and plan lines draw', () => {
  assert.match(page, /const chartRange = !\(pos \|\| sold\) \? '1D' : heldDays > 180 \? '1Y' : '6M'/);
  assert.doesNotMatch(page, /Date\.now\(\)/); // pure render: the latest bar, not the clock
  assert.match(page, /initialRange=\{chartRange\}/);
});

test('the verdict shows once above the tabs, inside the position card, with Why opening Details', () => {
  assert.match(position, /reasonFact\(first, v\.facts, v\.limits\)/);
  assert.match(position, /onClick=\{onDetails\}/);
  assert.match(page, /onDetails=\{\(\) => \{ setTab\('details'\)/);
  assert.doesNotMatch(page, /<Badge kind=\{verdictKind/); // no second SELL in the header
});

test('a one-buy holding shows only its term and tax, not the same qty and gain again', () => {
  assert.match(position, /const oneLot = lots\.length === 1/);
  assert.match(position, /lots\.length > 0 && !oneLot/);
});

test('how it has done: returns 1W to 1Y, sector, volume against its average', () => {
  assert.match(facts, /\['1w', '1W'\][\s\S]*\['1y', '1Y'\]/);
  assert.match(facts, /c\.sector, c\.industry/);
  assert.match(facts, /c\.volume \/ c\.avg_volume/);
});
