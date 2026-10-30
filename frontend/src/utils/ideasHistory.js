/** Idea history: the picks and forward records not scored yet, soonest first, with how long until they are. */
import { daysUntil, todayIst } from './events.js';

export const waiting = (picks = [], records = [], today = todayIst()) =>
  [
    ...picks.filter((p) => !p.outcome && p.due_date).map((p) => ({ key: `p:${p._id}`, symbol: p.symbol, what: p.label, kind: 'Pick', due: p.due_date })),
    ...records.filter((r) => !r.outcome && r.due_date).map((r) => ({ key: `r:${r.id}`, symbol: r.symbol, what: r.side, kind: 'Forward', due: r.due_date })),
  ]
    .map((w) => ({ ...w, days: daysUntil(w.due, today) }))
    .sort((a, b) => a.due.localeCompare(b.due) || a.symbol.localeCompare(b.symbol));

/** The empty line of a scored section: when its first one is due. */
export const firstDue = (rows) => (rows.length ? rows.reduce((a, b) => (a.due <= b.due ? a : b)).due : null);
