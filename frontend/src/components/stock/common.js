export const day = (d) => (d ? new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : '—');

const LABEL = { REVIEW: 'Review first' };
export const verdictLabel = (v) => LABEL[v] || v;
// Badge kinds carry the tone; the label always carries the meaning.
export const verdictKind = (v) => (v === 'SELL' || v === 'REVIEW' ? 'alert' : v === 'ADD' ? 'proven' : 'neutral');
