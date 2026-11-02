// The markdown subset the AI summaries use (headings, paragraphs, bullet and numbered lists,
// **bold**, *italic*, ---), parsed into plain data so the page renders React elements, never HTML
// (AI text can quote news, so it is not trusted markup). Pure.

const AMOUNT = /[−-]?(?:₹|Rs\.?\s?)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:lakhs?|crores?|cr|L|k)\b)?/gi;

/** Block list: { type: 'heading', level, text } | { type: 'p', text } | { type: 'ul'|'ol', items } | { type: 'hr' }. */
export const parseBlocks = (text = '') => {
  const blocks = [];
  let para = [];
  let list = null;
  const flush = () => {
    if (para.length) blocks.push({ type: 'p', text: para.join(' ') });
    if (list) blocks.push(list);
    para = [];
    list = null;
  };
  for (const raw of String(text).split('\n')) {
    const line = raw.trim();
    let m;
    if (!line) flush();
    else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) { flush(); blocks.push({ type: 'hr' }); }
    else if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { flush(); blocks.push({ type: 'heading', level: m[1].length, text: m[2] }); }
    else if ((m = line.match(/^[-*•]\s+(.*)$/))) {
      if (para.length || list?.type !== 'ul') flush();
      list = list || { type: 'ul', items: [] };
      list.items.push(m[1]);
    } else if ((m = line.match(/^\d+[.)]\s+(.*)$/))) {
      if (para.length || list?.type !== 'ol') flush();
      list = list || { type: 'ol', items: [] };
      list.items.push(m[1]);
    } else {
      if (list) flush();
      para.push(line);
    }
  }
  flush();
  return blocks;
};

// Signed percents (+2.4%, −1.1%) take a gain/loss tone; unsigned ones stay plain.
const PCT = /(?<![\w.])[+−-]\d+(?:\.\d+)?\s?%/g;
// ALL-CAPS words that look like NSE tickers; only those the quote endpoint knows become chips.
const TICKER = /\b[A-Z][A-Z0-9&-]{2,14}\b/g;
// ponytail: a fixed stoplist of market words; a name it misses just asks for a quote that never comes.
const NOT_TICKERS = new Set(('NIFTY NIFTY50 SENSEX BANKNIFTY FINNIFTY NSE BSE SEBI RBI FII FIIS DII DIIS FPI IPO ETF ETFS '
  + 'RSI MACD EMA SMA ATR VWAP ORB PCR EPS ROE ROCE PAT EBITDA GDP CPI WPI USD INR USDINR YOY QOQ CEO CFO '
  + 'AND THE FOR NOT BUY SELL HOLD AI LTP OHLC MTM SIP NAV IST UTC THIS THAT WITH YOUR CNC MIS NRML GST TDS STT '
  + 'IT FMCG PSU NBFC AUM OK NEW TOP LOW HIGH').split(' '));

/** Up to `max` distinct ticker-like words in the text, first seen first. */
export const tickerCandidates = (text = '', max = 8) => [...new Set((String(text).match(TICKER) || [])
  .filter((w) => !NOT_TICKERS.has(w) && /[A-Z]{3}/.test(w)))].slice(0, max);

const tone = (raw) => (/^\s*[−-]/.test(raw) ? 'loss' : /^\s*\+/.test(raw) ? 'gain' : undefined);

const splitBy = (segments, re, mark) => segments.flatMap((seg) => {
  if (seg.amount || seg.symbol || seg.pct) return [seg];
  const out = [];
  let last = 0;
  for (const m of seg.text.matchAll(re)) {
    const extra = mark(m[0]);
    if (!extra) continue;
    if (m.index > last) out.push({ ...seg, text: seg.text.slice(last, m.index) });
    out.push({ ...seg, text: m[0], ...extra });
    last = m.index + m[0].length;
  }
  if (last < seg.text.length) out.push({ ...seg, text: seg.text.slice(last) });
  return out;
});

const splitAmounts = (text, style, symbols) => {
  let out = splitBy([{ ...style, text }], AMOUNT, (raw) => ({ amount: true, tone: tone(raw) }));
  out = splitBy(out, PCT, (raw) => ({ pct: true, tone: tone(raw) }));
  if (symbols?.size) out = splitBy(out, TICKER, (raw) => (symbols.has(raw) ? { symbol: raw } : null));
  return out;
};

/** Inline segments [{ text, bold?, italic?, amount?, pct?, tone?, symbol? }] for one line of text.
    `symbols` (a Set) marks known tickers. */
export const parseInline = (text = '', symbols = undefined) => {
  const out = [];
  // _x_ only at word edges, so snake_case ids (earnings_falling_3q) stay literal.
  const re = /\*\*(.+?)\*\*|(?<![\w])__(.+?)__(?![\w])|\*(?!\s)(.+?)\*|(?<![\w])_(?!\s)(.+?)_(?![\w])/g;
  let last = 0;
  for (const m of String(text).matchAll(re)) {
    if (m.index > last) out.push(...splitAmounts(text.slice(last, m.index), {}, symbols));
    if (m[1] || m[2]) out.push(...splitAmounts(m[1] || m[2], { bold: true }, symbols));
    else out.push(...splitAmounts(m[3] || m[4], { italic: true }, symbols));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...splitAmounts(String(text).slice(last), {}, symbols));
  return out.filter((s) => s.text);
};

/** The text with markdown marks removed (for one-line places). */
export const plainText = (text = '') => parseInline(String(text).replace(/^#{1,6}\s+/gm, '').replace(/^[-*•]\s+/gm, ''))
  .map((s) => s.text).join('');

/** The first paragraph-like text, skipping headings, rules and italic-only meta lines. */
export const firstBody = (text = '') => {
  const p = parseBlocks(text).find((b) => (b.type === 'p' && !/^\*[^*].*\*$/.test(b.text)) || b.type === 'ul' || b.type === 'ol');
  if (!p) return '';
  return plainText(p.type === 'p' ? p.text : p.items[0]);
};

export const COLLAPSED_UNITS = 5; // paragraphs + list items shown before "Read more" (headings are free)

/** The first `budget` paragraphs/list items, a list cut part-way when the budget ends inside it. */
export const collapseBlocks = (blocks, budget = COLLAPSED_UNITS) => {
  const out = [];
  let left = budget;
  for (const b of blocks) {
    if (left <= 0) break;
    if (b.type === 'ul' || b.type === 'ol') {
      out.push({ ...b, items: b.items.slice(0, left) });
      left -= Math.min(left, b.items.length);
    } else {
      out.push(b);
      if (b.type === 'p') left -= 1;
    }
  }
  while (out.length && out[out.length - 1].type !== 'p' && out[out.length - 1].type !== 'ul' && out[out.length - 1].type !== 'ol') out.pop();
  return out;
};

/** Paragraphs + list items in a block list. */
export const contentUnits = (blocks) => blocks.reduce((n, b) => n + (b.type === 'p' ? 1 : b.items ? b.items.length : 0), 0);

export const LEAD_ITEMS = 3;

/** Key points first: `lead` is the first paragraph or up to LEAD_ITEMS list items, `intro` the rest
    before the first heading, `sections` one per heading ({ title, blocks }) for tap-to-expand. */
export const outline = (blocks) => {
  const clean = blocks.filter((b, i, all) => !(b.type === 'hr' && (i === 0 || i === all.length - 1)));
  const at = clean.findIndex((b) => b.type === 'heading');
  const head = at === -1 ? clean : clean.slice(0, at);
  const sections = [];
  for (const b of at === -1 ? [] : clean.slice(at)) {
    if (b.type === 'heading') sections.push({ title: b.text, blocks: [] });
    else if (b.type !== 'hr') sections[sections.length - 1].blocks.push(b);
  }
  const live = sections.filter((s) => s.blocks.length);
  let i = head.findIndex((b) => b.type === 'p' || b.type === 'ul' || b.type === 'ol');
  if (i === -1 && live.length) {  // everything sits under headings: the first section leads
    const [first, ...rest] = live;
    return { lead: first.blocks[0], leadTitle: first.title, intro: first.blocks.slice(1), sections: rest };
  }
  if (i === -1) return { lead: null, intro: head, sections: live };
  const b = head[i];
  const lead = b.items ? { ...b, items: b.items.slice(0, LEAD_ITEMS) } : b;
  const spill = b.items && b.items.length > LEAD_ITEMS ? [{ ...b, items: b.items.slice(LEAD_ITEMS) }] : [];
  return { lead, intro: [...spill, ...head.slice(i + 1)], sections: live };
};

/** 2-3 follow-up questions built from the text, no model call. */
export const followUps = (text = '', symbols = []) => {
  const plain = plainText(text).toLowerCase();
  const qs = symbols.slice(0, 2).map((s) => `Why ${s}?`);
  if (/\b(buy|sell|exit|hold|trim|add)\b/.test(plain)) qs.push('What should I do now?');
  else qs.push('What does this mean for me?');
  if (qs.length < 3) qs.push('Explain this simply');
  return qs.slice(0, 3);
};
