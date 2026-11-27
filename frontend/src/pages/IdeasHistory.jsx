import React, { useCallback, useState } from 'react';
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
import StockIcon from '../components/ui/StockIcon';
import Stat from '../components/ui/Stat';
import Tabs, { useTabParam } from '../components/ui/Tabs';

const nice = (n) => String(n || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const day = (d) => new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });

/** One scored idea: result after costs, and the plain verdict against NIFTY (word plus sign, never colour alone). */
const Line = ({ symbol, title, sub, net, excess, tag }) => (
  <li className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
    <StockIcon symbol={symbol} className="size-8" />
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2 min-w-0"><span className="text-[15px] font-medium text-[var(--text)] truncate">{title}</span>{tag && <Badge kind="neutral">{tag}</Badge>}</div>
      <div className="text-[13px] text-[var(--text-muted)] truncate">{sub}</div>
    </div>
    <div className="shrink-0 text-right tabular-nums">
      <div className={`text-[15px] font-semibold ${toneText(tone(net))}`}>{pct(net, { sign: true, dp: 1 })}</div>
      <div className={`text-[13px] ${toneText(tone(excess))}`}>{excess >= 0 ? 'Beat' : 'Lagged'} NIFTY {pct(excess, { sign: true, dp: 1 })}</div>
    </div>
  </li>
);

/** Counts over the loaded rows: how many were scored, how many ended up and how many beat NIFTY. */
const Summary = ({ rows }) => {
  const n = rows.length;
  const up = rows.filter((r) => r.net > 0).length;
  const beat = rows.filter((r) => r.excess >= 0).length;
  const share = (k) => (n ? pct(k / n, { dp: 0 }) : '–');
  return (
    <div className="mb-3 pb-3 border-b border-[var(--border)]" aria-label={`${n} scored · ${up} ended up · ${beat} beat NIFTY`}>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Scored" value={n} />
        <Stat label="Ended up" value={share(up)} delta={`${up} of ${n}`} />
        <Stat label="Beat NIFTY" value={share(beat)} delta={`${beat} of ${n}`} tone={n && beat / n >= 0.5 ? 'gain' : 'loss'} />
      </div>
    </div>
  );
};

const PAGE = 30; // rows shown before "Show more"

/** A long list in pages: the first PAGE rows, then a button for the next PAGE. */
const Paged = ({ items, render }) => {
  const [shown, setShown] = useState(PAGE);
  return (
    <>
      <ul>{items.slice(0, shown).map(render)}</ul>
      {items.length > shown && (
        <Button variant="secondary" className="mt-3 w-full" onClick={() => setShown((k) => k + PAGE)}>
          Show {Math.min(PAGE, items.length - shown)} more of {items.length - shown}
        </Button>
      )}
    </>
  );
};

const Section = ({ title, state, rows, note, empty, items, render }) => (
  <Card title={title} action={<Badge kind="paper">Paper</Badge>}>
    {state.loading ? <Skeleton rows={3} />
      : state.error ? <ErrorLine message="Could not load this." onRetry={state.reload} />
      : state.data.length === 0 ? <Empty title={empty} body="Ideas are scored once their holding period ends. Open ideas are on the Ideas page." action={<Link to="/ideas"><Button variant="secondary">See open ideas</Button></Link>} />
      : <><Summary rows={rows} />{note && <p className="-mt-1 mb-3 text-[13px] text-[var(--text-muted)]">{note}</p>}<Paged items={items} render={render} /></>}
  </Card>
);

const TABS = ['picks', 'forward', 'waiting'];

/** Picks history and scored forward records, newest first, one view at a time (Picks / Forward / Waiting). Admin data. */
const IdeasHistory = () => {
  const [tab, setTab] = useTabParam(TABS);
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
  const recomputed = (picks.data || []).filter((p) => p.backfilled).length;
  const pending = waiting(allPicks.data || [], allRecords.data || []);
  const soonest = (kind) => firstDue(pending.filter((w) => w.kind === kind));
  const emptyLine = (none, kind) => (soonest(kind) ? `${none}: the first is scored on ${day(soonest(kind))}` : none);

  return (
    <Layout>
      <PageHeader title="Idea history" back="/ideas" />
      <div className="space-y-4">
        <p className="text-[13px] text-[var(--text-muted)]">Paper results, not your own trades. Net = after costs. NIFTY is the benchmark each idea is judged against.</p>
        <Tabs label="History views" value={tab} onChange={setTab} tabs={[
          { id: 'picks', label: 'Picks', badge: picks.data?.length || 0 },
          { id: 'forward', label: 'Forward', badge: records.data?.length || 0 },
          { id: 'waiting', label: 'Waiting', badge: pending.length },
        ]} />
        {tab === 'picks' && (
          <Section title="Scored picks" state={picks}
            rows={(picks.data || []).filter((p) => !p.backfilled).map((p) => ({ net: p.outcome.net, excess: p.outcome.net - p.outcome.nifty }))}
            note={recomputed ? `Figures above count the ${picks.data.length - recomputed} picks scored live, the same record as Ideas. ${recomputed} more below were recomputed after the fact and are not in it.` : null} empty={emptyLine('No scored picks yet', 'Pick')}
            items={picks.data || []} render={(p) => (
              <Line key={p._id} symbol={p.symbol} title={bareSymbol(p.symbol)} sub={`${day(p.date)} · ${p.horizon}d · ${p.label}`} tag={p.backfilled ? 'Recomputed' : null}
                net={p.outcome.net} excess={p.outcome.net - p.outcome.nifty} />
            )} />
        )}
        {tab === 'forward' && (
          <Section title="Scored records" state={records} rows={(records.data || []).map((r) => ({ net: r.outcome.net, excess: r.outcome.excess }))} empty={emptyLine('Nothing scored yet', 'Forward')}
            items={records.data || []} render={(r) => (
              <Line key={r.id} symbol={r.symbol} title={`${bareSymbol(r.symbol)} · ${r.side}`} sub={`${day(r.decided_at)} · ${nice(r.name)}`}
                net={r.outcome.net} excess={r.outcome.excess} />
            )} />
        )}
        {tab === 'waiting' && (
          <Card title="Waiting to be scored" action={<Badge kind="neutral">{pending.length}</Badge>}>
            {pending.length === 0 ? <Empty title="Nothing waiting" body="Every idea so far has been scored." /> : (
              <Paged items={pending} render={(w) => (
                <li key={w.key} className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
                  <StockIcon symbol={w.symbol} className="size-8" />
                  <div className="min-w-0 flex-1">
                    <div className="text-[15px] font-medium text-[var(--text)] truncate">{bareSymbol(w.symbol)}{w.what ? ` · ${w.what}` : ''}</div>
                    <div className="text-[13px] text-[var(--text-muted)]">{w.kind}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-[14px] font-semibold text-[var(--text)]">{day(w.due)}</div>
                    <div className="text-[13px] text-[var(--text-muted)]">{countdown(w.days)}</div>
                  </div>
                </li>
              )} />
            )}
          </Card>
        )}
      </div>
    </Layout>
  );
};

export default IdeasHistory;
