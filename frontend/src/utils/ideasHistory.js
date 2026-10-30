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

const short = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' });

/** A Handled row's line: what was done and when, and when a snoozed one comes back. */
export const handledSub = (h) => [
  h.state === 'snoozed' ? 'Snoozed' : 'Dismissed',
  h.at && short(h.at),
  h.state === 'snoozed' && h.until && `back on ${short(h.until)}`,
].filter(Boolean).join(' · ');

/** Rows hidden before titles were kept show their id's readable part ("stop_hit:A:90" -> "stop hit · A"). */
export const handledTitle = (h) => h.title || h.action_id.split(':').slice(0, 2).join(' · ').replace(/_/g, ' ');
