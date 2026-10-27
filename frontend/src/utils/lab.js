const DASH = '–';

export const strategiesState = (b) => {
  if (!b) return DASH;
  const s = b.strategies || [];
  if (!s.length) return 'No strategies';
  return `${s.length} strategies · ${s.filter((x) => x.live_switch === true).length} live`;
};

export const runsState = (b, now = Date.now()) => {
  if (!b) return DASH;
  const r = (b.runs || [])[0];
  if (!r) return 'No runs yet';
  // Mongo hands back naive UTC (no offset); read it as UTC, not the browser's local time.
  const at = /Z|[+-]\d\d:?\d\d$/.test(r.created_at) ? r.created_at : `${r.created_at}Z`;
  const days = Math.floor((now - Date.parse(at)) / 86400000);
  return days < 1 ? 'Last run today' : `Last run ${days}d ago`;
};

export const forwardState = (b) => {
  if (!b) return DASH;
  const n = (b.rows || []).reduce((s, r) => s + (r.n || 0), 0);
  return n ? `${n} scored` : 'Nothing scored yet';
};

/** `null` is a 404 (no report built yet); `undefined` is a failed read. */
export const newsAccuracyState = (b) => {
  if (b === undefined) return DASH;
  if (b === null) return 'No report yet';
  const d = new Date(b.as_of).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  return `Built ${d}${b.company_scan_ok === false ? ' · company scan off' : ''}`;
};

export const handbookState = (b) => {
  if (!b) return DASH;
  const failing = Object.entries(b).filter(([k, v]) => k !== 'as_of' && v?.error).length;
  return failing ? `${failing} failing` : 'All checks ok';
};

export const backlogState = (b) => {
  if (!b) return DASH;
  return `${(b.items || []).filter((i) => i.status !== 'done' && i.status !== 'dropped').length} open`;
};

export const betaState = (b) => (b ? `${b.returned_from_last_week} of ${b.active_last_week} came back` : DASH);
