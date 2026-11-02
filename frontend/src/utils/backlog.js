// The admin backlog (pages/Backlog.jsx): stages, the one-tap advance, search, grouping and times. Pure.

import { formatDateTime, formatTimeAgo } from './formatters.js';

export const AREAS = ['System', 'Data', 'Trading', 'AI', 'News', 'Journal', 'UI', 'Ops', 'Product'];
export const EFFORTS = ['S', 'M', 'L'];
export const STAGES = [['idea', 'Idea'], ['next', 'Next'], ['doing', 'Doing'], ['done', 'Done'], ['dropped', 'Dropped']];
// Phone tabs: Now is what is being worked on or up next.
export const VIEWS = [
  { id: 'now', label: 'Now', statuses: ['doing', 'next'] },
  { id: 'idea', label: 'Ideas', statuses: ['idea'] },
  { id: 'done', label: 'Done', statuses: ['done'] },
  { id: 'dropped', label: 'Dropped', statuses: ['dropped'] },
];
// One chart colour per area, so a row's dot says where it belongs at a glance.
export const AREA_COLOR = Object.fromEntries(AREAS.map((a, i) => [a, `var(--chart-${(i % 6) + 1})`]));

/** The one-tap move forward: Idea -> Next -> Doing -> Done; none for Done/Dropped. */
export const advance = (status) => ({
  idea: { to: 'next', label: 'Next' },
  next: { to: 'doing', label: 'Start' },
  doing: { to: 'done', label: 'Done' },
}[status] || null);

/** Items matching the search (title, why, notes), area and effort; '' means any. */
export const filterItems = (items, { q = '', area = '', effort = '' } = {}) => {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return (items || []).filter((i) => (!area || i.area === area) && (!effort || i.effort === effort)
    && words.every((w) => `${i.title} ${i.why || ''} ${i.notes || ''}`.toLowerCase().includes(w)));
};

/** One status's items in rank order. */
export const byStatus = (items, status) => items.filter((i) => i.status === status).sort((a, b) => a.rank - b.rank);

/** Count per status over all items (the summary strip ignores filters). */
export const counts = (items) => Object.fromEntries(STAGES.map(([s]) => [s, (items || []).filter((i) => i.status === s).length]));

/** The one time a collapsed row shows, by stage: "started 2h ago"; '' when the item has none. */
export const stageTime = (item) => {
  const [word, at] = {
    doing: item.started_at ? ['started', item.started_at] : ['added', item.created_at],
    done: ['done', item.done_at],
    dropped: ['dropped', item.updated_at],
  }[item.status] || ['added', item.created_at];
  return at ? `${word} ${formatTimeAgo(at)}` : '';
};

/** Every time an item has, in order, for the open editor; empty ones are left out. */
export const timeline = (item) => [
  ['Added', item.created_at], ['Started', item.started_at], ['Done', item.done_at], ['Updated', item.updated_at],
].filter(([, at]) => at).map(([label, at]) => ({ label, at: formatDateTime(at) }));
