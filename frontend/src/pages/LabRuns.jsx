import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { LAB_TABS } from '../components/layout/sections';
import { Sheet, Empty } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { compareRows } from '../utils/labRuns';
import { formatTimeAgo } from '../utils/formatters';

/** Research Lab run records (admin-only, /lab/runs): newest first; tick two to compare side by side. */

const fmt = (v) => (typeof v === 'number' ? v.toFixed(3) : '—');
const TH = 'text-left font-normal field-label py-1 pr-3';
const TD = 'py-1.5 pr-3 align-top';

const LabRuns = () => {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState([]);
  const [comparing, setComparing] = useState(false);

  useEffect(() => {
    api.get(endpoints.labRuns.list)
      .then((res) => setRuns(res.data.runs))
      .catch((err) => setError(err.response?.data?.detail || 'Could not load runs.'));
  }, []);

  const toggle = (id) => {
    setComparing(false);
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length < 2 ? [...p, id] : p));
  };
  const [a, b] = picked.map((id) => runs.find((r) => r.id === id));

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-4xl">
        <SectionTabs tabs={LAB_TABS} label="Lab" />
        <Sheet title="Runs" meta={runs ? `${runs.length} latest` : undefined}
               actions={<button type="button" disabled={picked.length !== 2} onClick={() => setComparing(true)}
                                className="min-h-11 sm:min-h-8 px-3 border border-[var(--rule-strong)] text-sm disabled:opacity-40">Compare</button>}>
          {error && <p role="alert" className="text-sm text-[var(--loss)]">{error}</p>}
          {!error && runs === null && <p className="doc-meta">Loading…</p>}
          {runs && runs.length === 0 && <Empty title="No runs recorded yet" />}
          {runs && runs.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr><th className={TH}><span className="sr-only">Compare</span></th><th className={TH}>Created</th><th className={TH}>Kind</th><th className={TH}>Name</th>
                    <th className={TH}>Window</th><th className={TH}>Code</th><th className={TH}>CAGR</th><th className={TH}>Sharpe</th><th className={TH}>Max DD</th></tr>
                </thead>
                <tbody className="divide-y divide-[var(--rule)]">
                  {runs.map((r) => (
                    <tr key={r.id}>
                      <td className={TD}>
                        <input type="checkbox" aria-label={`Compare ${r.kind} ${r.name}`} checked={picked.includes(r.id)}
                               disabled={!picked.includes(r.id) && picked.length === 2} onChange={() => toggle(r.id)} />
                      </td>
                      <td className={TD}>{formatTimeAgo(r.created_at)}</td>
                      <td className={TD}>{r.kind}</td>
                      <td className={TD}>{r.name}</td>
                      <td className={`${TD} whitespace-nowrap`}>{r.window?.join(' → ')}</td>
                      <td className={`${TD} font-mono`}>{(r.code_sha || '').slice(0, 7)}</td>
                      <td className={TD}>{fmt(r.metrics?.cagr)}</td>
                      <td className={TD}>{fmt(r.metrics?.sharpe)}</td>
                      <td className={TD}>{fmt(r.metrics?.max_drawdown)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Sheet>
        {comparing && a && b && (
          <Sheet title="Compare" meta={`${a.kind}/${a.name} vs ${b.kind}/${b.name}`}>
            {compareRows(a, b).length === 0 ? <Empty title="These runs share no numeric metrics" /> : (
              <table className="w-full text-sm">
                <thead><tr><th className={TH}>Metric</th><th className={TH}>{a.name} · {(a.code_sha || '').slice(0, 7)}</th><th className={TH}>{b.name} · {(b.code_sha || '').slice(0, 7)}</th></tr></thead>
                <tbody className="divide-y divide-[var(--rule)]">
                  {compareRows(a, b).map((row) => (
                    <tr key={row.key}><td className={TD}>{row.key}</td><td className={TD}>{fmt(row.a)}</td><td className={TD}>{fmt(row.b)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Sheet>
        )}
      </div>
    </Layout>
  );
};

export default LabRuns;
