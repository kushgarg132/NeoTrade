import React, { useCallback, useState } from 'react';
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
import { formatClock } from '../../utils/formatters';
import { Segmented } from '../settings/Fields';
import { STATUSES, groupActivity, sourceLabel, sources, tally } from '../../utils/activity';

/** AI -> Activity: the autopilot's orders and refusals (last 200) with their reasons, grouped by day, with a
 *  status and source filter and a sort. */
const SELECT = 'min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 text-[14px] text-[var(--text)]';

const Activity = ({ state, plan }) => {
  const [status, setStatus] = useState('all');
  const [source, setSource] = useState('all');
  const [sort, setSort] = useState('newest');
  const summary = useLoad(useCallback(() => api.get(endpoints.summaries.activity).then((r) => r.data), []));
  const top = <AiSummary title="What the AI did today and why" state={summary} emptyBody="Written after the close on days the AI acts or plans." />;
  if (state.error) return <ErrorLine message="Couldn't load the AI's activity." onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={4} />;
  const rows = state.data?.rows || [];
  if (rows.length === 0) return <div className="space-y-3">{top}<PlanCard data={plan} /><Empty title="Nothing from the AI yet" body="Every order and refusal shows here with its reason, once the autopilot is on."
    action={<Link to="/settings/autopilot" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold">Check autopilot in Settings</Link>} /></div>;
  const groups = groupActivity(rows, { status, source, sort });
  return (
    <div className="space-y-3">
    {top}
    <PlanCard data={plan} />
    <div className="flex flex-wrap items-center justify-between gap-2">
      <Segmented label="Filter by result" options={STATUSES} value={status} onChange={setStatus} />
      <div className="flex gap-2">
        <select aria-label="Filter by source" value={source} onChange={(e) => setSource(e.target.value)} className={SELECT}>
          {sources(rows).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} className={SELECT}>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </select>
      </div>
    </div>
    {!groups.length && <Empty title="Nothing matches" body="No order or refusal fits these filters." />}
    {groups.map(([label, list]) => (
      <Card key={label} title={label} action={<span className="text-[13px] text-[var(--text-muted)]">{tally(list)}</span>}>
        <ul>
          {list.map((r, i) => (
            <li key={`${r.at}-${i}`} className="py-2 border-b border-[var(--border)] last:border-b-0">
              <div className="flex items-center gap-2 flex-wrap text-[15px] text-[var(--text)]">
                <Badge kind={String(r.mode).toUpperCase() === 'LIVE' ? 'live' : 'paper'}>{String(r.mode).toUpperCase() === 'LIVE' ? 'Live' : 'Paper'}</Badge>
                <Badge kind={r.status === 'FILLED' ? 'proven' : r.status === 'SENT' ? 'neutral' : 'alert'}>{r.status}</Badge>
                <span className="font-medium">{r.side} {r.quantity} {r.symbol}</span>
              </div>
              <div className="text-[13px] text-[var(--text-muted)]">{[r.source && sourceLabel(r.source), r.at && formatClock(r.at)].filter(Boolean).join(' · ')}</div>
              {r.reason && <p className="mt-0.5 text-[14px] text-[var(--text)]">{r.reason}</p>}
            </li>
          ))}
        </ul>
      </Card>
    ))}
    </div>
  );
};

export default Activity;
