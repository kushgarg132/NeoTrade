// Helpers for showing stored AI text. Pure.

const AMOUNT = /(?:₹|Rs\.?\s?)\d[\d,]*(?:\.\d+)?(?:\s?(?:lakhs?|crores?|cr|k)\b)?/gi;

/** Text cut into [{ text, amount }] so rupee amounts can wear the privacy mask (`.figure-md`). */
export const splitAmounts = (text = '') => {
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(AMOUNT)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), amount: false });
    parts.push({ text: m[0], amount: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), amount: false });
  return parts;
};

const sentences = (text) => (text || '').trim().match(/[^.!?]+(?:[.!?]+|$)/g)?.map((s) => s.trim()).filter(Boolean) || [];
const RISK = /\b(risks?|downside|could|may fall|however|but|headwinds?|concerns?|threats?|if the|unless)\b/i;

/** A thesis as { why, risk }: from the first sentence (after the opening one) that names a risk. No such sentence: all `why`. */
export const splitThesis = (text) => {
  const all = sentences(text);
  const at = all.findIndex((s, i) => i > 0 && RISK.test(s));
  if (at < 0) return { why: all.join(' '), risk: '' };
  return { why: all.slice(0, at).join(' '), risk: all.slice(at).join(' ') };
};

/** The first sentence, cut to `max` characters with an ellipsis. */
export const oneLine = (text, max = 160) => {
  const first = sentences(text)[0] || '';
  return first.length > max ? `${first.slice(0, max - 1).trimEnd()}…` : first;
};
