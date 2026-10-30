import React, { useCallback } from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import { Link } from 'react-router-dom';
import { useLoad } from '../components/ideas/useLoad';
import { useAuth } from '../context/AuthContext';
import api, { endpoints } from '../utils/api';
import { bareSymbol } from '../utils/formatters';
import { pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import { countdown } from '../utils/events';
import { firstDue, waiting } from '../utils/ideasHistory';

const nice = (n) => String(n || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const day = (d) => new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });

/** One scored idea: result after costs, and the plain verdict against NIFTY (word plus sign, never colour alone). */
const Line = ({ title, sub, net, excess }) => (
  <li className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
    <div className="min-w-0 flex-1">
      <div className="text-[15px] font-medium text-[var(--text)] truncate">{title}</div>
      <div className="text-[13px] text-[var(--text-muted)] truncate">{sub}</div>
    </div>
    <div className="shrink-0 text-right tabular-nums">
      <div className={`text-[15px] font-semibold ${toneText(tone(net))}`}>{pct(net, { sign: true })}</div>
      <div className={`text-[13px] ${toneText(tone(excess))}`}>{excess >= 0 ? 'Beat' : 'Lagged'} NIFTY {pct(excess, { sign: true })}</div>
    </div>
  </li>
);

/** Counts over the loaded rows: how many were scored, how many ended up and how many beat NIFTY. */
const Summary = ({ rows }) => {
  const n = rows.length;
  const up = rows.filter((r) => r.net > 0).length;
  const beat = rows.filter((r) => r.excess >= 0).length;
  return (
    <p className="mb-2 text-[14px] text-[var(--text)] tabular-nums">
      <b>{n}</b> scored · <b>{up}</b> ended up · <b>{beat}</b> beat NIFTY
    </p>
  );
};

const Section = ({ title, state, rows, empty, children }) => (
  <Card title={title} action={<Badge kind="paper">Paper</Badge>}>
    {state.loading ? <Skeleton rows={3} />
      : state.error ? <ErrorLine message="Could not load this." onRetry={state.reload} />
      : state.data.length === 0 ? <Empty title={empty} body="Ideas are scored once their holding period ends. Open ideas are on the Ideas page." action={<Link to="/ideas"><Button variant="secondary">See open ideas</Button></Link>} />
      : <><Summary rows={rows} /><ul>{children}</ul></>}
  </Card>
);

/** Picks history and scored forward records, newest first. Admin data. */
const IdeasHistory = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  // Everything loads; scored ones fill Picks / Forward records, the rest "Waiting to be scored".
  const allPicks = useLoad(useCallback(() => (isAdmin
    ? api.get(endpoints.picks.history(90)).then((r) => r.data.picks)
    : Promise.resolve([])), [isAdmin]));
  const allRecords = useLoad(useCallback(() => (isAdmin
    ? api.get(endpoints.forward.records).then((r) => r.data.records)
    : Promise.resolve([])), [isAdmin]));
  const picks = { ...allPicks, data: allPicks.data && allPicks.data.filter((p) => p.outcome) };
  const records = { ...allRecords, data: allRecords.data && allRecords.data.filter((x) => x.outcome && 'excess' in x.outcome)
    .sort((a, b) => String(b.decided_at).localeCompare(String(a.decided_at))) };
  const pending = waiting(allPicks.data || [], allRecords.data || []);
  const soonest = (kind) => firstDue(pending.filter((w) => w.kind === kind));
  const emptyLine = (none, kind) => (soonest(kind) ? `${none}: the first is scored on ${day(soonest(kind))}` : none);

  return (
    <Layout>
      <PageHeader title="Idea history" back="/ideas" />
      <div className="space-y-4">
        <p className="text-[13px] text-[var(--text-muted)]">Paper results, not your own trades. Net = after costs. NIFTY is the benchmark each idea is judged against.</p>
        <Section title="Picks" state={picks} rows={(picks.data || []).map((p) => ({ net: p.outcome.net, excess: p.outcome.net - p.outcome.nifty }))} empty={emptyLine('No scored picks yet', 'Pick')}>
          {picks.data?.map((p) => (
            <Line key={p._id} title={`${bareSymbol(p.symbol)} · ${p.label}`} sub={`${day(p.date)} · ${p.horizon}d hold`}
              net={p.outcome.net} excess={p.outcome.net - p.outcome.nifty} />
          ))}
        </Section>
        <Section title="Forward records" state={records} rows={(records.data || []).map((r) => ({ net: r.outcome.net, excess: r.outcome.excess }))} empty={emptyLine('Nothing scored yet', 'Forward')}>
          {records.data?.map((r) => (
            <Line key={r.id} title={`${bareSymbol(r.symbol)} · ${r.side}`} sub={`${day(r.decided_at)} · ${nice(r.name)}`}
              net={r.outcome.net} excess={r.outcome.excess} />
          ))}
        </Section>
        {pending.length > 0 && (
          <Card title="Waiting to be scored" action={<Badge kind="neutral">{pending.length}</Badge>}>
            <ul>
              {pending.map((w) => (
                <li key={w.key} className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
                  <div className="min-w-0 flex-1">
                    <div className="text-[15px] font-medium text-[var(--text)] truncate">{bareSymbol(w.symbol)}{w.what ? ` · ${w.what}` : ''}</div>
                    <div className="text-[13px] text-[var(--text-muted)]">{w.kind}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-[14px] font-semibold text-[var(--text)]">{day(w.due)}</div>
                    <div className="text-[13px] text-[var(--text-muted)]">{countdown(w.days)}</div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </Layout>
  );
};

export default IdeasHistory;
