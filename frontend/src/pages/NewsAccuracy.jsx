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
import { SCOPES, HORIZONS, MEASURES, rowsFor, hitTone } from '../utils/newsAccuracy';

/** Lab › News accuracy (admin-only): did scored news point the way prices then went?
 *  Built weekly by the ingest worker (backend/datalayer/accuracy.py). */

const SELECT = 'min-h-11 px-3 rounded-[12px] bg-[var(--surface-2)] border border-[var(--border)] text-[15px] text-[var(--text)]';

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
            <select aria-label="Scope" className={SELECT} value={scope} onChange={(e) => setScope(e.target.value)}>
              {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select aria-label="Horizon" className={SELECT} value={horizon} onChange={(e) => setHorizon(e.target.value)}>
              {HORIZONS.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
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
              <table className="w-full text-[14px] tabular-nums">
                <thead className="text-[12px] text-[var(--text-muted)] text-left">
                  <tr><th className="py-1 pr-2">Group</th><th className="pr-2">Impact</th><th className="pr-2">Measure</th>
                    <th className="pr-2 text-right">n</th><th className="pr-2 text-right">Hit rate</th>
                    <th className="pr-2 text-right">Mean</th><th className="text-right">t</th></tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={`${c.group}|${c.key}|${c.impact}|${c.measure}`}
                        className={`border-t border-[var(--border)] ${c.thin ? 'opacity-50' : ''}`}>
                      <td className="py-1 pr-2 whitespace-nowrap">{c.key === 'all' ? 'All' : `${c.group} · ${c.key}`}</td>
                      <td className="pr-2">{c.impact}</td>
                      <td className="pr-2 whitespace-nowrap text-[var(--text-muted)]">{MEASURES[c.measure] || c.measure}</td>
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
    </SettingsPage>
  );
};

export default NewsAccuracy;
