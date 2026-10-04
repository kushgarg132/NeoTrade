const GAP = {
  days: (c) => `${c.need - c.have} more paper days`,
  trades: (c) => `${c.need - c.have} more trades`,
  net: () => 'a net profit',
  profit_factor: (c) => `profit factor ${c.need} (now ${c.have ?? '–'})`,
  max_drawdown_pct: (c) => `drawdown under ${c.need}% (now ${c.have}%)`,
};

// What a strategy still lacks before its live switch sends real orders.
export function promotionGaps(row) {
  const last = row.backtest;
  const gaps = row.backtest_passed
    ? []
    : [
        last
          ? `a passing backtest (last: ${last.trades} trades over ${last.days} days, profit factor ${last.profit_factor?.toFixed(2) ?? '–'})`
          : 'a passing backtest (none run yet)',
      ];
  for (const check of row.paper.checks) if (!check.ok) gaps.push(GAP[check.rule](check));
  return gaps.join(', ');
}

// One line on whether a strategy has earned real money yet. `row` is its
// promotion row (undefined before it has any record); `isLive` is its switch.
export function readiness(row, isLive) {
  if (!row) return 'No paper record yet.';
  if (row.eligible) return `Ready for real money · live switch ${isLive ? 'on' : 'off'}`;
  return `${isLive ? 'Live switch on, still trading paper' : 'Paper only'}. Needs ${promotionGaps(row)}.`;
}

// The same record in a few words, for a one-line row: backtest mark, then
// paper days and trades against what promotion needs.
export function shortStatus(row) {
  if (!row) return 'no paper record yet';
  if (row.eligible) return 'ready';
  const mark = row.backtest_passed ? '✓' : row.backtest ? '✗' : '–';
  const parts = [`backtest ${mark}`];
  for (const rule of ['days', 'trades']) {
    const check = row.paper.checks.find((c) => c.rule === rule);
    if (check) parts.push(`${check.have}/${check.need} ${rule}`);
  }
  return parts.join(' · ');
}
