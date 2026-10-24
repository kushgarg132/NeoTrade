import React, { useCallback } from 'react';
import { Link } from 'react-router-dom';
import Card from '../ui/Card';
import Badge from '../ui/Badge';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import PlanCard from '../plan/PlanCard';
import AiSummary from './AiSummary';
import { useLoad } from '../ideas/useLoad';
import api, { endpoints } from '../../utils/api';
import { formatDateTime } from '../../utils/formatters';

/** AI -> Activity: every autopilot order and refusal with its reason, newest first. */
const Activity = ({ state, plan }) => {
  const summary = useLoad(useCallback(() => api.get(endpoints.summaries.activity).then((r) => r.data), []));
  const top = <AiSummary title="What the AI did today and why" state={summary} emptyBody="Written after the close on days the AI acts or plans." />;
  if (state.error) return <ErrorLine message="Couldn't load the AI's activity." onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={4} />;
  const rows = state.data?.rows || [];
  if (rows.length === 0) return <div className="space-y-3">{top}<PlanCard data={plan} /><Empty title="Nothing from the AI yet" body="Every order and refusal shows here with its reason, once the autopilot is on."
    action={<Link to="/settings?tab=limits" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold">Check autopilot in Limits</Link>} /></div>;
  return (
    <div className="space-y-3">
    {top}
    <PlanCard data={plan} />
    <Card title="Last 30" action={<Badge kind="paper">Paper</Badge>}>
      <ul>
        {rows.map((r, i) => (
          <li key={`${r.at}-${i}`} className="py-2 border-b border-[var(--border)] last:border-b-0">
            <div className="flex items-center gap-2 flex-wrap text-[15px] text-[var(--text)]">
              <Badge kind={r.status === 'FILLED' ? 'proven' : r.status === 'SENT' ? 'neutral' : 'alert'}>{r.status}</Badge>
              <span className="font-medium">{r.side} {r.quantity} {r.symbol}</span>
            </div>
            <div className="text-[13px] text-[var(--text-muted)]">{[r.source, r.mode, formatDateTime(r.at)].filter(Boolean).join(' · ')}</div>
            {r.reason && <p className="mt-0.5 text-[14px] text-[var(--text)]">{r.reason}</p>}
          </li>
        ))}
      </ul>
    </Card>
    </div>
  );
};

export default Activity;
