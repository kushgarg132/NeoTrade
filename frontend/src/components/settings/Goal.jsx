import React, { useEffect, useState } from 'react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import api, { endpoints, getPreferences } from '../../utils/api';
import { cn } from '../../utils/cn';

const KINDS = [['value', 'Reach a value'], ['beat_nifty', 'Beat NIFTY']];
const KIND_HELP = {
  value: 'Your portfolio value reaches the target amount by the date.',
  beat_nifty: 'Your portfolio return stays ahead of NIFTY 50 by this many percentage points by the date.',
};
const input = 'w-full min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 text-[15px] tabular-nums text-[var(--text)] focus:outline-none focus:border-[var(--accent)]';

/** Settings › Goal: one target and a date; Home tracks it. */
const Goal = () => {
  const [form, setForm] = useState(null);
  const [failed, setFailed] = useState(false);
  const [msg, setMsg] = useState(null); // { ok, text }
  const [busy, setBusy] = useState(false);

  const load = () => getPreferences()
    .then((r) => { const g = r.data.goal; setForm({ kind: g?.kind || 'value', target: g ? String(g.target) : '', by: g?.by || '' }); setFailed(false); })
    .catch(() => setFailed(true));
  useEffect(() => { load(); }, []);

  if (failed) return <Card title="Goal"><ErrorLine message="Couldn't load your goal. Home can't track it until this loads." onRetry={load} /></Card>;
  if (!form) return <Card title="Goal"><Skeleton rows={3} /></Card>;

  const set = (k, v) => { setForm({ ...form, [k]: v }); setMsg(null); };
  const save = async () => {
    setBusy(true);
    try {
      await api.put(endpoints.settings.preferences, { goal: { kind: form.kind, target: Number(form.target), by: form.by } });
      setMsg({ ok: true, text: 'Saved. Home now tracks this.' });
    } catch (e) {
      const d = e?.response?.data?.detail;
      setMsg({ ok: false, text: Array.isArray(d) ? d.map((x) => x.msg).join('; ') : d || 'Could not save.' });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api.delete(endpoints.settings.goal);
      setForm({ kind: 'value', target: '', by: '' });
      setMsg({ ok: true, text: 'Goal removed.' });
    } catch {
      setMsg({ ok: false, text: 'Could not remove the goal.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Goal">
      <div className="space-y-4">
        <div role="group" aria-label="Goal type" className="flex gap-2">
          {KINDS.map(([id, label]) => (
            <button key={id} type="button" aria-pressed={form.kind === id} onClick={() => set('kind', id)}
              className={cn('flex-1 min-h-11 rounded-[12px] border text-[15px] font-medium',
                form.kind === id ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]' : 'border-[var(--border)] text-[var(--text-muted)]')}>
              {label}
            </button>
          ))}
        </div>
        <p className="text-[14px] text-[var(--text-muted)]">{form.target ? KIND_HELP[form.kind] : `No goal set yet. ${KIND_HELP[form.kind]} Enter a target and a date, then save.`}</p>
        <label className="block">
          <span className="text-[13px] font-medium text-[var(--text-muted)]">
            {form.kind === 'value' ? 'Target value (₹)' : 'Points ahead of NIFTY (%)'}
          </span>
          <input type="number" inputMode="decimal" min="0" value={form.target} onChange={(e) => set('target', e.target.value)} className={cn(input, 'mt-1')} />
        </label>
        <label className="block">
          <span className="text-[13px] font-medium text-[var(--text-muted)]">By</span>
          <input type="date" value={form.by} onChange={(e) => set('by', e.target.value)} className={cn(input, 'mt-1')} />
        </label>
        {msg && <p role={msg.ok ? 'status' : 'alert'} className={cn('text-[14px]', msg.ok ? 'text-[var(--gain)]' : 'text-[var(--loss)]')}>{msg.text}</p>}
        <Button onClick={save} disabled={busy || !form.target || !form.by} className="w-full">{busy ? 'Saving…' : 'Save goal'}</Button>
        {form.target && <Button variant="secondary" onClick={remove} disabled={busy} className="w-full">Remove goal</Button>}
        <p className="text-[13px] text-[var(--text-muted)]">Progress counts from the day you save, at your portfolio's value then. Editing the target or date keeps that start.</p>
      </div>
    </Card>
  );
};

export default Goal;
