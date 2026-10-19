const MIN_N = 100;

/** The proven/unproven label for one (source, name) in the scorecard rows; null when it has no scored records yet. */
export const badgeFor = (rows, source, name) => {
  const row = (rows || []).find((r) => r.source === source && r.name === name);
  if (!row) return null;
  if (row.label === 'proven') return { text: 'Proven', tone: 'success' };
  return { text: `Unproven ${Math.min(row.n, MIN_N)}/${MIN_N}`, tone: 'neutral' };
};

export const pct = (v, digits = 2) => (v == null ? '–' : `${(v * 100).toFixed(digits)}%`);
