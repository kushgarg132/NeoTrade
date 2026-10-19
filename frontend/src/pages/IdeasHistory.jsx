import React, { useCallback } from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import { useLoad } from '../components/ideas/useLoad';
import { useAuth } from '../context/AuthContext';
import api, { endpoints } from '../utils/api';
import { bareSymbol } from '../utils/formatters';
import { pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';

const Line = ({ title, sub, net, vs }) => (
  <li className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
    <div className="min-w-0 flex-1">
      <div className="text-[15px] font-medium text-[var(--text)] truncate">{title}</div>
      <div className="text-[13px] text-[var(--text-muted)] truncate">{sub}</div>
    </div>
    <div className="shrink-0 text-right tabular-nums">
      <div className={`text-[15px] font-semibold ${toneText(tone(net))}`}>{pct(net, { sign: true })}</div>
      <div className="text-[12px] text-[var(--text-muted)]">{vs}</div>
    </div>
  </li>
);

const Section = ({ title, state, empty, children }) => (
  <Card title={title}>
    {state.loading ? <Skeleton rows={3} />
      : state.error ? <ErrorLine message="Could not load this." onRetry={state.reload} />
      : state.data.length === 0 ? <Empty title={empty} />
      : <ul>{children}</ul>}
  </Card>
);

/** Picks history and scored forward records, newest first. Admin data. */
const IdeasHistory = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const picks = useLoad(useCallback(() => (isAdmin
    ? api.get(endpoints.picks.history(90)).then((r) => r.data.picks.filter((p) => p.outcome))
    : Promise.resolve([])), [isAdmin]));
  const records = useLoad(useCallback(() => (isAdmin
    ? api.get(endpoints.forward.records).then((r) => r.data.records.filter((x) => x.outcome && 'excess' in x.outcome)
      .sort((a, b) => String(b.decided_at).localeCompare(String(a.decided_at))))
    : Promise.resolve([])), [isAdmin]));

  return (
    <Layout>
      <PageHeader title="Idea history" back="/ideas" />
      <div className="space-y-4">
        <Section title="Picks" state={picks} empty="No scored picks yet">
          {picks.data?.map((p) => (
            <Line key={p._id} title={`${bareSymbol(p.symbol)} · ${p.label}`} sub={`${p.date} · ${p.horizon}d`}
              net={p.outcome.net} vs={`NIFTY ${pct(p.outcome.nifty, { sign: true })}`} />
          ))}
        </Section>
        <Section title="Forward records" state={records} empty="Nothing scored yet">
          {records.data?.map((r) => (
            <Line key={r.id} title={`${bareSymbol(r.symbol)} · ${r.side}`} sub={`${String(r.decided_at).slice(0, 10)} · ${r.name}`}
              net={r.outcome.net} vs={`vs NIFTY ${pct(r.outcome.excess, { sign: true })}`} />
          ))}
        </Section>
      </div>
    </Layout>
  );
};

export default IdeasHistory;
