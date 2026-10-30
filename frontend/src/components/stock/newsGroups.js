import { formatNoteDate } from '../../utils/formatters.js';

export const FILTERS = [['all', 'All'], ['up', 'Positive'], ['down', 'Negative'], ['material', 'High impact']];
const KEEP = {
  all: () => true,
  up: (r) => r.direction > 0,
  down: (r) => r.direction < 0,
  material: (r) => r.material,
};

/** The IST calendar day of `at`, as "Today", "Yesterday" or "28 OCT 2026". */
export const dayLabel = (at, now = new Date()) => {
  if (!at) return 'Undated';
  const day = (d) => formatNoteDate(new Date(d));
  if (day(at) === day(now)) return 'Today';
  if (day(at) === day(now.getTime() - 86_400_000)) return 'Yesterday';
  return day(at);
};

/** `rows` filtered, sorted and grouped by IST day: [[label, rows]]. Days run newest first (oldest
 *  first for `oldest`); `impact` sorts within a day, biggest first. Undated rows go last. */
export const groupNews = (rows, filter, sort, now = new Date()) => {
  const time = (r) => (r.at ? new Date(r.at).getTime() : 0);
  const kept = rows.filter(KEEP[filter]).sort((a, b) => {
    if (!a.at !== !b.at) return a.at ? -1 : 1;
    const day = sort === 'oldest' ? time(a) - time(b) : time(b) - time(a);
    if (sort !== 'impact' || dayLabel(a.at, now) !== dayLabel(b.at, now)) return day;
    return (b.impact ?? -1) - (a.impact ?? -1) || day;
  });
  const groups = new Map();
  for (const r of kept) {
    const label = dayLabel(r.at, now);
    groups.set(label, [...(groups.get(label) || []), r]);
  }
  return [...groups];
};
