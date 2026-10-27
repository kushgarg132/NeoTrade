import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
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
import { compareRows, flatMetrics, fmtMetric } from '../utils/labRuns';
import { formatTimeAgo } from '../utils/formatters';

/** Research Lab run records (admin-only, /lab/runs): newest first; tick two to compare side by side.
 *  Every figure is a backtest/research result, never a live-account figure: the Paper badge says so. */

const SIGNED = ['cagr', 'alpha'];
// Return-like keys carry a sign so a loss is never colour alone.
const fm = (key, v) => (SIGNED.includes(key) && typeof v === 'number' ? pct(v, { sign: true, dp: 1 }) : fmtMetric(key, v));
const diff = (key, a, b) => {
  if (typeof a !== 'number' || typeof b !== 'number') return '—';
  const d = b - a;
  if (['cagr', 'max_drawdown', 'volatility', 'alpha'].includes(key)) return `${d > 0 ? '+' : d < 0 ? '-' : ''}${Math.abs(d * 100).toFixed(1)} pts`;
  return `${d > 0 ? '+' : d < 0 ? '-' : ''}${Math.abs(d).toFixed(key === 'sharpe' || key === 'sortino' || key === 'beta' ? 2 : 3)}`;
};

const Metric = ({ label, value, valueTone = 'neutral' }) => (
  <div className="min-w-0">
    <div className="text-[12px] text-[var(--text-muted)]">{label}</div>
    <div className={`figure-md text-[15px] tabular-nums ${toneText(valueTone)}`}>{value}</div>
  </div>
);

const LabRuns = () => {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState([]);
  const [comparing, setComparing] = useState(false);

  const load = useCallback(() => {
    api.get(endpoints.labRuns.list)
      .then((res) => { setError(null); setRuns(res.data?.runs ?? []); })
      .catch(() => setError("Couldn't load the Lab runs."));
  }, []);
  useEffect(load, [load]);

  const toggle = (id) => {
    setComparing(false);
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length < 2 ? [...p, id] : p));
  };
  const [a, b] = picked.map((id) => (runs ?? []).find((r) => r.id === id));
  const rowsCmp = comparing && a && b ? compareRows(a, b) : [];

  return (
    <SettingsPage title="Runs" back="/settings/lab" backLabel="Lab" right={<Badge kind="paper">Paper · backtests</Badge>}>
        <Card
          title={runs ? `${runs.length} latest` : 'Latest runs'}
          action={<Button variant="secondary" disabled={picked.length !== 2} onClick={() => setComparing(true)}>Compare</Button>}
        >
          <p className="mb-2 text-[13px] text-[var(--text-muted)]">
            {picked.length === 2 ? 'Two runs picked. Tap Compare.' : `Pick two runs to compare (${picked.length}/2).`}{' '}
            CAGR = yearly growth · Sharpe = return per unit of risk · Max DD = worst peak-to-trough fall.
          </p>
          {error && <ErrorLine message={error} onRetry={load} />}
          {!error && runs === null && <Skeleton rows={4} />}
          {runs && runs.length === 0 && (
            <Empty
              title="No runs recorded yet"
              body="A run is saved each time a backtest, retune or factor study finishes in the Lab."
              action={<Link to="/settings/lab/strategies" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold">Open Strategies</Link>}
            />
          )}
          {runs && runs.length > 0 && (
            <div>
              {runs.map((r) => {
                const m = flatMetrics(r.metrics);
                const on = picked.includes(r.id);
                return (
                  <label key={r.id} className="flex items-start gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
                    <input type="checkbox" className="mt-1 w-5 h-5 shrink-0 accent-[var(--accent)]" aria-label={`Compare ${r.kind} ${r.name}`}
                           checked={on} disabled={!on && picked.length === 2} onChange={() => toggle(r.id)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[15px] font-medium text-[var(--text)] truncate">{r.name}</span>
                        <Badge>{r.kind}</Badge>
                      </div>
                      <div className="text-[12px] text-[var(--text-muted)]">
                        {r.window?.join(' → ')} · {formatTimeAgo(r.created_at)}{r.code_sha ? <> · <span className="font-mono">{r.code_sha.slice(0, 7)}</span></> : null}
                      </div>
                      <div className="mt-1 grid grid-cols-3 gap-2">
                        <Metric label="CAGR" value={fm('cagr', m.cagr)} valueTone={tone(m.cagr)} />
                        <Metric label="Sharpe" value={fm('sharpe', m.sharpe)} />
                        <Metric label="Max DD" value={fm('max_drawdown', m.max_drawdown)} />
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          )}
        </Card>
        {comparing && a && b && (
          <Card title="Compare" action={<Badge kind="paper">Paper</Badge>}>
            <p className="mb-2 text-[13px] text-[var(--text-muted)]">{a.kind}/{a.name} (A) vs {b.kind}/{b.name} (B). Difference = B minus A.</p>
            {rowsCmp.length === 0 ? <Empty title="These runs share no numeric metrics" body="Pick two runs of the same kind to compare." /> : (
              <div className="overflow-x-auto">
                <table className="w-full text-[14px] tabular-nums">
                  <thead>
                    <tr className="text-left text-[12px] text-[var(--text-muted)]">
                      <th className="font-normal py-1 pr-3">Metric</th>
                      <th className="font-normal py-1 pr-3">A · {(a.code_sha || '').slice(0, 7)}</th>
                      <th className="font-normal py-1 pr-3">B · {(b.code_sha || '').slice(0, 7)}</th>
                      <th className="font-normal py-1">Difference</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {rowsCmp.map((row) => (
                      <tr key={row.key} className="min-h-11">
                        <td className="py-2 pr-3">{row.key}</td>
                        <td className="py-2 pr-3">{fm(row.key, row.a)}</td>
                        <td className="py-2 pr-3">{fm(row.key, row.b)}</td>
                        <td className="py-2">{diff(row.key, row.a, row.b)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}
    </SettingsPage>
  );
};

export default LabRuns;
