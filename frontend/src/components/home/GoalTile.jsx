import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Target, ChevronRight } from 'lucide-react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Badge from '../ui/Badge';
import { inr, pct } from '../ui/format';
import api, { endpoints, getPreferences } from '../../utils/api';
import { progress } from '../../utils/goal';

const PACE = { ahead: ['proven', 'Ahead'], on: ['neutral', 'On pace'], behind: ['unproven', 'Behind'] };
const month = (d) => new Date(`${d}T00:00:00Z`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric', timeZone: 'UTC' });

/** Home: how far along the owner's goal is. Own fetches, so a failure only blanks this card. */
const GoalTile = () => {
  const [state, setState] = useState({ loading: true });

  const load = useCallback(() => {
    Promise.all([
      getPreferences(),
      api.get(endpoints.mine.overview).catch(() => null),
      api.get(endpoints.mine.history('ALL')).catch(() => null),
    ])
      .then(([prefs, overview, history]) => setState({ goal: prefs.data.goal, overview: overview?.data, history: history?.data }))
      .catch(() => setState({ failed: true }));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (state.failed) return <Card title="Goal"><ErrorLine message="Could not load your goal." onRetry={() => { setState({ loading: true }); load(); }} /></Card>;
  if (state.loading) return <Card title="Goal"><Skeleton rows={2} /></Card>;
  const { goal } = state;
  if (!goal) {
    return (
      <Link to="/settings?tab=goal" className="flex items-center gap-3 min-h-11 rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-4 active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
        <Target className="w-5 h-5 text-[var(--accent)]" aria-hidden="true" />
        <span className="text-[15px] font-semibold text-[var(--text)]">Set a goal</span>
        <span className="flex-1 text-[13px] text-[var(--text-muted)]">Home will track it</span>
        <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
      </Link>
    );
  }

  const p = progress(goal, state.overview, state.history);
  const [kind, label] = PACE[p.pace];
  const what = goal.kind === 'value' ? `${inr(goal.target)} by ${month(goal.by)}` : `NIFTY +${goal.target}% by ${month(goal.by)}`;
  const monthly = p.neededMonthly != null && Number.isFinite(p.neededMonthly) && p.neededMonthly > 0 ? `needs ${pct(p.neededMonthly, { dp: 1 })} a month` : null;
  return (
    <Card title="Goal" action={<Badge kind={kind}>{label}</Badge>}>
      <Link to="/settings?tab=goal" className="block active:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
        <p className="flex items-center justify-between gap-2 text-[15px] text-[var(--text)]"><span className="private">{what}</span><ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" /></p>
        <div className="mt-2 h-2 rounded-full bg-[var(--surface-2)]" role="progressbar" aria-valuenow={Math.round(p.pct * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Goal progress">
          <div className="h-2 rounded-full bg-[var(--accent)]" style={{ width: `${p.pct * 100}%` }} />
        </div>
        <p className="mt-2 text-[13px] text-[var(--text-muted)] tabular-nums">
          {Math.round(p.pct * 100)}% there{monthly && ` · ${monthly}`}
          {p.actualMonthly != null && ` · last 3 months ${pct(p.actualMonthly, { dp: 1, sign: true })} a month`}
        </p>
      </Link>
    </Card>
  );
};

export default GoalTile;
