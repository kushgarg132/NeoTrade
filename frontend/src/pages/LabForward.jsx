import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { LAB_TABS } from '../components/layout/sections';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import PageHeader from '../components/ui/PageHeader';
import { pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import api, { endpoints } from '../utils/api';

/** Lab › Forward (admin-only, /lab/forward): every decision the system recorded, scored later; tap a row for its records.
 *  Figures are paper (recorded, not traded) results, net of charges, excess over NIFTY. */

const gateText = (g) => (g === null || g === undefined ? 'No gate yet' : g ? 'Gate passes' : 'Gate fails');
const sp = (v, dp = 2) => pct(v, { sign: true, dp });

const Metric = ({ label, value, valueTone = 'neutral' }) => (
  <div className="min-w-0">
    <div className="text-[12px] text-[var(--text-muted)]">{label}</div>
    <div className={`figure-md text-[15px] tabular-nums ${toneText(valueTone)}`}>{value}</div>
  </div>
);

const Records = ({ records }) => (records === null ? <Skeleton rows={3} /> : records.length === 0 ? (
  <p className="py-2 text-[14px] text-[var(--text-muted)]">No records for this one yet. They appear as decisions are recorded.</p>
) : (
  <div>
    {records.map((x) => {
      const o = x.outcome;
      const net = o && !o.void ? o.net : null;
      return (
        <div key={x.id} className="flex items-center gap-3 min-h-9 py-1 text-[14px] border-b border-[var(--border)] last:border-b-0">
          <span className="font-mono text-[12px] text-[var(--text-muted)] w-[5.5rem] shrink-0">{String(x.decided_at).slice(0, 10)}</span>
          <span className="flex-1 min-w-0 truncate font-medium">{x.symbol} <span className="text-[12px] text-[var(--text-muted)]">{x.side}</span></span>
          <span className={`figure-md tabular-nums ${toneText(tone(net))}`}>{o ? (o.void ? 'void' : sp(o.net)) : 'pending'}</span>
          <span className="w-20 text-right text-[12px] text-[var(--text-muted)] tabular-nums">{o && !o.void ? `NIFTY ${sp(o.nifty)}` : ''}</span>
        </div>
      );
    })}
  </div>
));

const LabForward = () => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [records, setRecords] = useState(null);

  const load = useCallback(() => {
    setError(null);
    api.get(endpoints.forward.scorecard)
      .then((res) => setRows(res.data?.rows ?? []))
      .catch(() => setError("Couldn't load the forward record."));
  }, []);
  useEffect(load, [load]);

  const pick = (row) => {
    setRecords(null);
    const key = `${row.source}:${row.name}`;  // by value: a refetched row is a new object
    if (open === key) return setOpen(null);
    setOpen(key);
    api.get(endpoints.forward.records, { params: { source: row.source, name: row.name } })
      .then((res) => setRecords(res.data?.records ?? []))
      .catch(() => setRecords([]));
  };

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-4xl">
        <SectionTabs tabs={LAB_TABS} label="Lab" />
        <PageHeader title="Forward" right={<Badge kind="paper">Paper</Badge>} />
        <Card title="Scored decisions">
          <p className="mb-2 text-[13px] text-[var(--text-muted)]">
            Net of charges, excess over NIFTY. Proven needs 100 scored, t of 2 or more, and calibration.
            n/100 = decisions scored so far · t = how far the average is from luck · Hit rate = share that beat NIFTY · Calibration gap = stated confidence minus actual hit rate.
          </p>
          {error && <ErrorLine message={error} onRetry={load} />}
          {!error && rows === null && <Skeleton rows={4} />}
          {rows && rows.length === 0 && (
            <Empty title="Nothing scored yet" body="Decisions are recorded as they happen and scored after their horizon, in the 16:00 IST pass. Run a strategy on paper to start the record."
                   action={<Link to="/settings/lab/strategies" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold">Open Strategies</Link>} />
          )}
          {rows && rows.length > 0 && rows.map((r) => {
            const key = `${r.source}:${r.name}`;
            const isOpen = open === key;
            return (
              <div key={key} className="border-b border-[var(--border)] last:border-b-0">
                <button type="button" onClick={() => pick(r)} aria-expanded={isOpen}
                        className="w-full min-h-14 py-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[15px] font-medium text-[var(--text)] truncate">{r.name}</span>
                    <span className="text-[12px] text-[var(--text-muted)]">{r.source}</span>
                    <span className="ml-auto flex items-center gap-1 shrink-0">
                      {r.disagrees && <Badge kind="alert">Disagrees</Badge>}
                      <Badge kind={r.label === 'proven' ? 'proven' : 'unproven'}>{r.label}</Badge>
                    </span>
                  </div>
                  <div className="mt-1 grid grid-cols-4 gap-2">
                    <Metric label="Mean excess" value={sp(r.mean_excess)} valueTone={tone(r.mean_excess)} />
                    <Metric label="t" value={r.t == null ? '—' : r.t.toFixed(2)} />
                    <Metric label="Hit rate" value={pct(r.hit_rate, { dp: 1 })} />
                    <Metric label="Calib. gap" value={sp(r.calibration_gap, 1)} />
                  </div>
                  <div className="mt-1 text-[12px] text-[var(--text-muted)]">
                    {r.progress}/100 scored{r.n > r.progress ? ` (${r.n} total)` : ''} · {gateText(r.gate)}
                  </div>
                </button>
                {isOpen && <div className="pb-2 pl-2"><Records records={records} /></div>}
              </div>
            );
          })}
        </Card>
      </div>
    </Layout>
  );
};

export default LabForward;
