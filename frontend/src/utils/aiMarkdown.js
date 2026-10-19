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

const splitAmounts = (text, style) => {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(AMOUNT)) {
    if (m.index > last) out.push({ ...style, text: text.slice(last, m.index) });
    out.push({ ...style, text: m[0], amount: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ ...style, text: text.slice(last) });
  return out;
};

/** Inline segments [{ text, bold?, italic?, amount? }] for one line of text. */
export const parseInline = (text = '') => {
  const out = [];
  // _x_ only at word edges, so snake_case ids (earnings_falling_3q) stay literal.
  const re = /\*\*(.+?)\*\*|(?<![\w])__(.+?)__(?![\w])|\*(?!\s)(.+?)\*|(?<![\w])_(?!\s)(.+?)_(?![\w])/g;
  let last = 0;
  for (const m of String(text).matchAll(re)) {
    if (m.index > last) out.push(...splitAmounts(text.slice(last, m.index), {}));
    if (m[1] || m[2]) out.push(...splitAmounts(m[1] || m[2], { bold: true }));
    else out.push(...splitAmounts(m[3] || m[4], { italic: true }));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...splitAmounts(String(text).slice(last), {}));
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
