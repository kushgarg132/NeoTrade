// Helpers for the AI summary cards (backend/summaries/).

const AMOUNT = /([−-]?₹\s?\d+(?:,\d{2,3})*(?:\.\d+)?(?:\s?(?:cr|crore|lakh|L|k))?)/gi;

/** A summary's text as parts, rupee amounts marked so the hide-amounts toggle can blur them. */
export const amountParts = (text) =>
  String(text || '').split(AMOUNT).map((part, i) => ({ text: part, amount: i % 2 === 1 })).filter((p) => p.text);

/** A summary's lines, empty ones dropped. */
export const summaryLines = (text) => String(text || '').split('\n').map((l) => l.trim()).filter(Boolean);
