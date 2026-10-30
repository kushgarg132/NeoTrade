/** AI -> Activity: the autopilot log filtered, sorted and grouped by IST day. */
import { dayLabel } from '../components/stock/newsGroups.js';

export const STATUSES = [['all', 'All'], ['FILLED', 'Filled'], ['REFUSED', 'Refused']];
const SOURCE = { engine: 'Engine', picks: 'Picks', news: 'News', plan: 'Game plan' };
export const sourceLabel = (s) => SOURCE[s] || String(s || 'Other').replace(/^./, (c) => c.toUpperCase());

/** The sources present, for the filter: [['all','All sources'], ['engine','Engine'], ...]. */
export const sources = (rows = []) => [['all', 'All sources'], ...[...new Set(rows.map((r) => r.source).filter(Boolean))].sort().map((s) => [s, sourceLabel(s)])];

/** [[day label, rows]], days and rows newest first ('oldest' flips both). Other statuses (SENT...) show under All only. */
export const groupActivity = (rows = [], { status = 'all', source = 'all', sort = 'newest' } = {}, now = new Date()) => {
  const kept = rows
    .filter((r) => (status === 'all' || r.status === status) && (source === 'all' || r.source === source))
    .sort((a, b) => (sort === 'oldest' ? 1 : -1) * String(a.at).localeCompare(String(b.at)));
  const groups = new Map();
  for (const r of kept) {
    const label = dayLabel(r.at, now);
    groups.set(label, [...(groups.get(label) || []), r]);
  }
  return [...groups];
};

/** A day's tally: "3 filled · 5 refused". */
export const tally = (rows) => {
  const n = (s) => rows.filter((r) => r.status === s).length;
  return [n('FILLED') && `${n('FILLED')} filled`, n('REFUSED') && `${n('REFUSED')} refused`].filter(Boolean).join(' · ');
};

/** A day's rows with its refusals folded: { shown (everything but REFUSED, in order), refused, reason (the most
 *  common refusal reason, null when there are none), reasonCount }. Pure. */
export const foldRefusals = (rows = []) => {
  const refused = rows.filter((r) => r.status === 'REFUSED');
  const counts = new Map();
  for (const r of refused) counts.set(r.reason || 'no reason given', (counts.get(r.reason || 'no reason given') || 0) + 1);
  const [reason, reasonCount] = [...counts].sort((a, b) => b[1] - a[1])[0] || [null, 0];
  return { shown: rows.filter((r) => r.status !== 'REFUSED'), refused, reason, reasonCount };
};
