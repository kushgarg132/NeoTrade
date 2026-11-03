// Helpers for the AI summary cards (backend/summaries/).

/** A summary's lines for line-by-line places: empty lines, rules and markdown heading/list marks dropped. */
export const summaryLines = (text) => String(text || '').split('\n')
  .map((l) => l.trim().replace(/^#{1,6}\s+/, '').replace(/^(?:[-*•]|\d+[.)])\s+/, ''))
  .filter((l) => l && !/^(-{3,}|\*{3,}|_{3,})$/.test(l));
