// Which Today sections show, in order, for each market phase (GET /today `phase`).
const ORDER = {
  pre: ['beforeOpen', 'picksTop', 'doToday', 'account', 'markets'],
  session: ['doToday', 'account', 'aiActivity', 'markets'],
  post: ['afterClose', 'journalPrompt', 'scoreboard', 'account', 'aiActivity'],
  closed: ['closedNote', 'afterClose', 'scoreboard', 'account'],
};

// An old backend sends no phase: fall back to the session order.
export const sectionsFor = (phase) => ORDER[phase] || ORDER.session;

const ENTITIES = { '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'", '&amp;': '&' };

/** A digest's Telegram HTML as plain lines: tags gone, entities decoded, leading emoji dropped. */
export const digestLines = (html) => {
  const lines = String(html || '')
    .replace(/<[^>]*>/g, '')
    .replace(/&(?:lt|gt|quot|#x27|amp);/g, (e) => ENTITIES[e])
    .split('\n');
  if (lines.length) lines[0] = lines[0].replace(/^[^\p{L}\p{N}]+/u, '');
  return lines.filter(Boolean);
};
