import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import Button from '../ui/Button';
import api, { endpoints } from '../../utils/api';

const num = (v) => (v === '' ? null : Number(v));
const INPUT = 'w-full min-h-11 px-3 py-2 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] text-[15px] text-[var(--text)]';

/** Why I bought, target, stop, review-by. PUT /mine/thesis/{symbol}; a 422 shows its reason inline. */
const ThesisEditor = ({ symbol, thesis, onSaved }) => {
  const [form, setForm] = useState({
    why: thesis?.why ?? '',
    target: thesis?.target ?? '',
    stop: thesis?.stop ?? '',
    review_by: thesis?.review_by ?? '',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const set = (k) => (e) => {
    setForm({ ...form, [k]: e.target.value });
    setSaved(false);
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.put(endpoints.mine.thesis(symbol), {
        why: form.why,
        target: num(form.target),
        stop: num(form.stop),
        review_by: form.review_by || null,
      });
      setSaved(true);
      onSaved?.(res.data);
    } catch (err) {
      const d = err?.response?.data?.detail;
      // FastAPI sends a string, or a list of {msg}.
      setError(typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : 'Could not save');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block">
        <span className="text-[13px] text-[var(--text-muted)]">Why I bought</span>
        <textarea value={form.why} onChange={set('why')} maxLength={2000} rows={3} className={`${INPUT} mt-1`} />
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label className="block">
          <span className="text-[13px] text-[var(--text-muted)]">Target price</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={form.target} onChange={set('target')} className={`${INPUT} mt-1`} />
        </label>
        <label className="block">
          <span className="text-[13px] text-[var(--text-muted)]">Stop price</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={form.stop} onChange={set('stop')} className={`${INPUT} mt-1`} />
        </label>
        <label className="block">
          <span className="text-[13px] text-[var(--text-muted)]">Review by</span>
          <input type="date" value={form.review_by} onChange={set('review_by')} className={`${INPUT} mt-1`} />
        </label>
      </div>
      {error && (
        <p role="alert" className="text-[14px] text-[var(--loss)]">
          {error}
        </p>
      )}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="secondary" disabled={busy}>
          {busy && <Loader2 className="w-4 h-4 animate-spin" />}
          Save thesis
        </Button>
        {saved && <span className="text-[13px] text-[var(--text-muted)]">Saved</span>}
      </div>
    </form>
  );
};

export default ThesisEditor;
