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

/** The time that fits an item's stage: when it started, finished or was dropped, else when it was added. */
const stageAt = (item) => ({
  doing: item.started_at, done: item.done_at, dropped: item.updated_at,
}[item.status]) || item.created_at;

/** One status's items, newest first by the time that fits the stage. */
export const byStatus = (items, status) => items.filter((i) => i.status === status)
  .sort((a, b) => new Date(stageAt(b) || 0) - new Date(stageAt(a) || 0));

/** Count per status over all items (the tab counts ignore filters). */
export const counts = (items) => Object.fromEntries(STAGES.map(([s]) => [s, (items || []).filter((i) => i.status === s).length]));

/** The one time a collapsed row shows, by stage: "started 2h ago"; '' when the item has none. */
export const stageTime = (item) => {
  const word = { doing: item.started_at && 'started', done: 'done', dropped: 'dropped' }[item.status] || 'added';
  const at = item.status === 'done' ? item.done_at : stageAt(item);
  return at ? `${word} ${formatTimeAgo(at)}` : '';
};

/** Every time an item has, in order, for the open editor; empty ones are left out. */
export const timeline = (item) => [
  ['Added', item.created_at], ['Started', item.started_at], ['Done', item.done_at], ['Updated', item.updated_at],
].filter(([, at]) => at).map(([label, at]) => ({ label, at: formatDateTime(at) }));
