// The admin backlog (pages/Backlog.jsx): stages, the one-tap advance, search and grouping. Pure.

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
