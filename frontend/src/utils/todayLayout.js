
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
