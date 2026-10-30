import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
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
import { STATUSES, foldRefusals, groupActivity, sourceLabel, sources, tally } from '../../utils/activity';

/** AI -> Activity: the autopilot's orders and refusals (last 200) with their reasons, grouped by day, with a
 *  status and source filter and a sort. */
const DOT = { FILLED: 'bg-[var(--gain)]', SENT: 'bg-[var(--warn)]', REFUSED: 'bg-[var(--text-muted)]' };
const WORD = { FILLED: 'Filled', SENT: 'Sent', REFUSED: 'Refused' };

/** One order or refusal on one line: status dot, side quantity symbol, its time and source, the reason under it.
 *  Live rows say so; paper is the page's default and goes unsaid. */
const Item = ({ r }) => {
  const live = String(r.mode).toUpperCase() === 'LIVE';
  return (
    <li className="flex gap-3 py-2.5 border-b border-[var(--border)] last:border-b-0">
      <span aria-hidden="true" className={`mt-[7px] w-2 h-2 shrink-0 rounded-full ${DOT[r.status] || 'bg-[var(--text-muted)]'}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <span className="min-w-0 truncate text-[15px] text-[var(--text)]">
            <span className="sr-only">{WORD[r.status] || r.status}: </span>
            <span className={r.status === 'REFUSED' ? 'text-[var(--text-muted)]' : 'font-semibold'}>{r.side} {r.quantity} {r.symbol}</span>
            {live && <span className="ml-2 align-middle"><Badge kind="live">Live</Badge></span>}
          </span>
          <span className="shrink-0 text-[12px] tabular-nums text-[var(--text-muted)]">{[r.source && sourceLabel(r.source), r.at && formatClock(r.at)].filter(Boolean).join(' · ')}</span>
        </div>
        {r.reason && <p className="text-[13px] text-[var(--text-muted)]">{r.reason}</p>}
      </div>
    </li>
  );
};

/** One day: its fills and other orders, then its refusals folded behind "N refused · <commonest reason>" unless the
 *  Refused filter asked for them. */
const Day = ({ label, list, fold }) => {
  const [open, setOpen] = useState(false);
  const f = foldRefusals(list);
  const rows = fold ? f.shown : list;
  return (
    <Card title={label} action={<span className="text-[13px] text-[var(--text-muted)]">{tally(list)}</span>}>
      {rows.length > 0 && <ul>{rows.map((r, i) => <Item key={`${r.at}-${i}`} r={r} />)}</ul>}
      {fold && f.refused.length > 0 && (
        <>
          <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
            className="tap mt-1 flex w-full min-h-11 items-center gap-2 rounded-[12px] text-left text-[14px] text-[var(--text-muted)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
            <ChevronRight className={`w-4 h-4 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden="true" />
            <span className="min-w-0 truncate"><span className="font-semibold">{f.refused.length} refused</span>{f.reason && ` · ${f.reason}${f.reasonCount < f.refused.length ? ' and others' : ''}`}</span>
          </button>
          {open && <ul className="fade-in">{f.refused.map((r, i) => <Item key={`${r.at}-r${i}`} r={r} />)}</ul>}
        </>
      )}
    </Card>
  );
};

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
    {groups.map(([label, list]) => <Day key={label} label={label} list={list} fold={status === 'all'} />)}
    </div>
  );
};

export default Activity;
