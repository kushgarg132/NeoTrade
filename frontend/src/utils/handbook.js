/** The handbook's sections and the live panels its markdown may place. */
export const HANDBOOK_TABS = [
  { id: 'system', label: 'System & Data' },
  { id: 'trading', label: 'Trading & Money' },
  { id: 'ai', label: 'AI & News' },
  { id: 'ops', label: 'Jobs & Ops' },
  { id: 'journey', label: 'Journey' },
];
export const PANELS = ['deploy', 'jobs', 'news', 'data', 'ai'];

/**
 * Handbook markdown carries `<!-- live:<panel> -->` lines where a live status
 * panel renders (invisible on GitHub). Splits a file into text and panel
 * parts; a marker naming an unknown panel is dropped and its text joined.
 */
const MARKER = /<!--\s*live:([\w-]+)\s*-->/;

export const splitLive = (markdown, known) => {
  const pieces = markdown.split(MARKER); // text, name, text, name, …
  const parts = [];
  let text = '';
  pieces.forEach((piece, index) => {
    if (index % 2 === 0) {
      text += piece;
    } else if (known.includes(piece)) {
      if (text) parts.push({ md: text });
      parts.push({ live: piece });
      text = '';
    }
  });
  if (text) parts.push({ md: text });
  return parts;
};
