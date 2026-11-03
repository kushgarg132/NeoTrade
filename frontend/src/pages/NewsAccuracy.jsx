import React, { useCallback, useEffect, useState } from 'react';
import SettingsPage from './SettingsPage';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import { pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import api, { endpoints } from '../utils/api';
import { Segmented } from '../components/settings/Fields';
import { SCOPES, HORIZONS, MEASURES, rowsFor, hitTone, barRows } from '../utils/newsAccuracy';

/** Lab › News accuracy (admin-only): did scored news point the way prices then went?
 *  Built weekly by the ingest worker (backend/datalayer/accuracy.py). */


const FilingLane = () => {
  const [lane, setLane] = useState(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => api.get(endpoints.newsFilings, { cache: false })
    .then((res) => { setLane(res.data); setFailed(false); })
    .catch(() => setFailed(true)), []);
  useEffect(() => { load(); }, [load]);

  return (
    <Card title="Filing lane" action={lane && <Badge kind={lane.bar.passes ? 'proven' : 'unproven'}>{lane.bar.passes ? 'Passed the bar' : 'Recording'}</Badge>}>
      <p className="mb-2 text-[13px] text-[var(--text-muted)]">
        Recording only. No trades. The rule: a filing with a clear direction, the price already moved 1% its way, held one hour.
      </p>
      {failed && <ErrorLine message="Couldn't load the filing lane." onRetry={load} />}
      {!failed && !lane && <Skeleton rows={4} />}
      {lane && (
        <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-[14px] tabular-nums">
          {barRows(lane.bar).map(([label, value]) => (
            <React.Fragment key={label}><dt className="text-[var(--text-muted)]">{label}</dt><dd className="text-right">{value}</dd></React.Fragment>
          ))}
          <dt className="text-[var(--text-muted)]">Long side alone</dt><dd className="text-right">{lane.bar.long_only.n} signals</dd>
          <dt className="text-[var(--text-muted)]">Median minutes to score</dt><dd className="text-right">{lane.health.median_lag_minutes ?? '–'}</dd>
          <dt className="text-[var(--text-muted)]">Waiting, failed, no PDF</dt><dd className="text-right">{lane.health.waiting}, {lane.health.failed}, {lane.health.pdf_failed}</dd>
          <dt className="text-[var(--text-muted)]">Quote not in filing, missed today</dt><dd className="text-right">{lane.health.key_fact_rejected}, {lane.health.gaps_today}</dd>
        </dl>
      )}
    </Card>
  );
};

const NewsAccuracy = () => {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [scope, setScope] = useState('COMPANY');
  const [horizon, setHorizon] = useState('5d');

  // No setState before the request: the first call runs inside an effect.
  const fetchReport = useCallback((refresh) => api.get(endpoints.newsAccuracy, { params: refresh ? { refresh: true } : {}, cache: false })
    .then((res) => { setError(null); setReport(res.data); })
    .catch((e) => (e?.response?.status === 404 ? setReport(false) : setError("Couldn't load the news accuracy report.")))
    .finally(() => setBusy(false)), []);
  useEffect(() => { fetchReport(false); }, [fetchReport]);
  const load = (refresh = false) => {
    setError(null);
    setBusy(refresh);
    fetchReport(refresh);
  };

  const rows = report ? rowsFor(report.cells, scope, horizon) : [];

  return (
    <SettingsPage title="News accuracy" back="/settings/lab" backLabel="Lab" right={report && (
      <Badge kind={report.company_scan_ok ? 'proven' : 'unproven'}>
        {report.company_scan_ok ? 'Company news passes' : 'Company news paused'}
      </Badge>
    )}>
        <Card title="Did the news point the right way?" action={
          <Button variant="secondary" onClick={() => load(true)} disabled={busy}>{busy ? 'Building…' : 'Rebuild now'}</Button>
        }>
          <p className="mb-2 text-[13px] text-[var(--text-muted)]">
            Items with a direction of 0.5 or more. Hit rate = share where the price moved the way the item said ·
            Mean = average move in the item's direction · t = how far that mean is from luck (days resampled) ·
            rows under 30 items are faded. Company news makes ideas again at a 52% hit over 300 items (5 days).
          </p>
          <div className="mb-2 flex flex-wrap gap-2">
            <Segmented fill label="Scope" options={SCOPES.map((v) => [v, `${v[0]}${v.slice(1).toLowerCase()}`])} value={scope} onChange={setScope} />
            <Segmented label="Horizon" options={HORIZONS.map((v) => [v, v])} value={horizon} onChange={setHorizon} />
          </div>
          {error && <ErrorLine message={error} onRetry={() => load()} />}
          {!error && report === null && <Skeleton rows={6} />}
          {report === false && (
            <Empty title="No report yet" body="The ingest worker builds it once a week from the news outcomes."
                   action={<Button onClick={() => load(true)} disabled={busy}>Build it now</Button>} />
          )}
          {report && rows.length === 0 && <p className="py-2 text-[14px] text-[var(--text-muted)]">No measured items for {scope} at {horizon} yet.</p>}
          {report && rows.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full table-fixed text-[14px] tabular-nums" aria-label="Hit rate by group">
                <thead className="text-[12px] text-[var(--text-muted)] text-left">
                  <tr><th className="py-1 pr-2">Group</th><th className="w-12 pr-2 text-right">n</th><th className="w-11 pr-2 text-right">Hit</th>
                    <th className="w-16 pr-2 text-right">Mean</th><th className="w-9 text-right">t</th></tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={`${c.group}|${c.key}|${c.impact}|${c.measure}`}
                        className={`border-t border-[var(--border)] ${c.thin ? 'opacity-50' : ''}`}>
                      <td className="py-1.5 pr-2 break-words">
                        {c.key === 'all' ? 'All' : `${c.group} · ${c.key}`}
                        <span className="block text-[12px] text-[var(--text-muted)]">{c.impact} · {MEASURES[c.measure] || c.measure}</span>
                      </td>
                      <td className="pr-2 text-right">{c.n}</td>
                      <td className={`pr-2 text-right ${toneText(hitTone(c))}`}>{pct(c.hit, { dp: 0 })}</td>
                      <td className={`pr-2 text-right ${toneText(c.thin ? 'neutral' : tone(c.mean))}`}>{pct(c.mean, { sign: true })}</td>
                      <td className="text-right">{c.t == null ? '—' : c.t.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {report && <p className="mt-2 text-[12px] text-[var(--text-muted)]">Built {new Date(report.as_of).toLocaleString()} from {report.rows} outcomes.</p>}
        </Card>
        <FilingLane />
    </SettingsPage>
  );
};

export default NewsAccuracy;
