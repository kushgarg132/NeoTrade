import React from 'react';
import Card from '../ui/Card';
import Badge from '../ui/Badge';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import PlanCard from '../plan/PlanCard';
import { formatDateTime } from '../../utils/formatters';

/** AI -> Activity: every autopilot order and refusal with its reason, newest first. */
const Activity = ({ state, plan }) => {
  if (state.error) return <ErrorLine message="Could not load the AI's activity." onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={4} />;
  const rows = state.data?.rows || [];
  if (rows.length === 0) return <div className="space-y-3"><PlanCard data={plan} /><Empty title="Nothing from the AI yet" body="Orders and refusals show here with their reasons." /></div>;
  return (
    <div className="space-y-3">
    <PlanCard data={plan} />
    <Card title="Last 30">
      <ul>
        {rows.map((r, i) => (
          <li key={`${r.at}-${i}`} className="py-2.5 border-b border-[var(--border)] last:border-b-0">
            <div className="flex items-center gap-2 flex-wrap text-[15px] text-[var(--text)]">
              <Badge kind={r.status === 'FILLED' ? 'proven' : r.status === 'SENT' ? 'neutral' : 'alert'}>{r.status}</Badge>
              <span className="font-medium">{r.side} {r.quantity} {r.symbol}</span>
            </div>
            <div className="mt-0.5 text-[13px] text-[var(--text-muted)]">{[r.source, r.mode, formatDateTime(r.at)].filter(Boolean).join(' · ')}</div>
            {r.reason && <p className="mt-0.5 text-[14px] text-[var(--text)]">{r.reason}</p>}
          </li>
        ))}
      </ul>
    </Card>
    </div>
  );
};

export default Activity;
