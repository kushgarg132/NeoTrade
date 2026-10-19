/** Sections a user may see: admin-only ones are dropped for everyone else. */
export const visibleSections = (sections, isAdmin) => sections.filter((s) => !s.admin || isAdmin);

// A literal lookup so Tailwind sees the class names.
const COLUMNS = { 4: 'grid-cols-4', 5: 'grid-cols-5', 6: 'grid-cols-6' };
export const barColumns = (count) => COLUMNS[count] || 'grid-cols-6';
