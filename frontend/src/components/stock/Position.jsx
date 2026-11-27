import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import Badge from '../ui/Badge';
import { REASONS } from '../../utils/mine';
import { reasonFact } from '../../utils/verdict';
import Card from '../ui/Card';
import Button from '../ui/Button';
import ErrorLine from '../ui/ErrorLine';
import Term from '../ui/Term';
import { NumberField } from '../settings/Fields';
import { inr, pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { px } from '../ideas/levels';
import { formatQuantity } from '../../utils/formatters';
import { formatXirr } from '../../utils/mine';
import api, { endpoints } from '../../utils/api';
import { day, verdictKind, verdictLabel } from './common';

const ring = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]';
const LOTS_SHOWN = 2; // more fold under "All N lots"

const Stat = ({ label, value, valueClass = '' }) => (
  <div className="min-w-0">
    <div className="text-[13px] text-[var(--text-muted)]">{label}</div>
    <div className={`private text-[15px] font-semibold tabular-nums truncate ${valueClass}`}>{value}</div>
  </div>
);

/** "Long-term in 75 days" / "Long-term" for one lot (Indian equity: held over a year). */
const lotTerm = (l) => (l.days_to_long > 0 ? `Long-term in ${l.days_to_long} days` : 'Long-term');

/** One buy lot: when, how many at what price, its gain now, and what selling it today would cost in tax. */
const Lot = ({ l }) => (
  <li className="flex items-start justify-between gap-3 py-2 border-b border-[var(--border)] last:border-b-0">
    <div className="min-w-0">
      <div className="text-[14px] text-[var(--text)] tabular-nums">
        {day(l.buy_date)} · <span className="private">{formatQuantity(l.qty)} @ {px(l.price)}</span>
      </div>
      <div className={`text-[13px] ${l.days_to_long > 0 ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}`}>{lotTerm(l)}</div>
    </div>
    <div className="shrink-0 text-right tabular-nums">
      {l.gain != null && <div className={`private text-[14px] font-semibold ${toneText(tone(l.gain))}`}>{inr(l.gain, { sign: true })}</div>}
      {l.est_tax > 0 && <div className="private text-[13px] text-[var(--text-muted)]">tax if sold ≈ {inr(l.est_tax)}</div>}
    </div>
  </li>
);

/** Your plan for the holding (PUT /mine/thesis/:symbol): why you hold it, a target and a stop (both raise alerts and
 *  draw on the chart) and a date to review it. Shown as one line, edited in place. */
const Plan = ({ symbol, thesis, onSaved }) => {
  const t = thesis || {};
  const has = t.why || t.target != null || t.stop != null || t.review_by;
  const [form, setForm] = useState(null); // null = reading
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const edit = () => setForm({ why: t.why || '', target: t.target ?? '', stop: t.stop ?? '', review_by: t.review_by || '' });
  const num = (v) => (v === '' || v == null ? null : Number(v));
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.put(endpoints.mine.thesis(symbol), { why: form.why, target: num(form.target), stop: num(form.stop), review_by: form.review_by || null });
      setForm(null);
      onSaved();
    } catch (err) {
      const d = err?.response?.data?.detail;
      setError(typeof d === 'string' ? d : Array.isArray(d) ? 'Stop must be below target, and both above zero.' : 'Could not save your plan.');
    } finally {
      setBusy(false);
    }
  };

  if (form) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap gap-3">
          <div><div className="mb-1 text-[13px] text-[var(--text-muted)]">Target</div>
            <NumberField label="Target price" prefix="₹" value={form.target} onChange={(v) => setForm({ ...form, target: v })} /></div>
          <div><div className="mb-1 text-[13px] text-[var(--text-muted)]">Stop</div>
            <NumberField label="Stop price" prefix="₹" value={form.stop} onChange={(v) => setForm({ ...form, stop: v })} /></div>
          <label className="block"><span className="mb-1 block text-[13px] text-[var(--text-muted)]">Review by</span>
            <input type="date" value={form.review_by} onChange={(e) => setForm({ ...form, review_by: e.target.value })}
              className="min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface-2)] px-3 text-[15px] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]" /></label>
        </div>
        <label className="block"><span className="mb-1 block text-[13px] text-[var(--text-muted)]">Why you hold it</span>
          <textarea rows={2} maxLength={2000} value={form.why} onChange={(e) => setForm({ ...form, why: e.target.value })}
            className="w-full rounded-[12px] border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-[15px] text-[var(--text)] focus:outline-none focus:border-[var(--accent)]" /></label>
        {error && <p role="alert" className="text-[14px] text-[var(--loss)]">{error}</p>}
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => { setForm(null); setError(null); }} disabled={busy}>Cancel</Button>
          <Button onClick={save} disabled={busy}>Save plan</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 text-[14px]">
        {has ? (
          <>
            <p className="tabular-nums text-[var(--text)]">
              {t.target != null && <>Target <span className="private font-semibold">{px(t.target)}</span></>}
              {t.target != null && t.stop != null && ' · '}
              {t.stop != null && <>Stop <span className="private font-semibold">{px(t.stop)}</span></>}
              {t.review_by && <span className="text-[var(--text-muted)]"> · review by {day(t.review_by)}</span>}
            </p>
            {t.why && <p className="mt-0.5 text-[var(--text-muted)] line-clamp-2">{t.why}</p>}
          </>
        ) : <p className="text-[var(--text-muted)]">No plan yet. A target and a stop raise alerts and show on the chart.</p>}
      </div>
      <Button variant="secondary" className="shrink-0 px-3 text-[14px]" onClick={edit}>{has ? 'Edit' : 'Set plan'}</Button>
    </div>
  );
};

/**
 * Your side of the stock, above the tabs: quantity at average, P&L, value and weight, XIRR and how long you have
 * held it, the stop line, your buy lots with days to long-term and the tax a sale would cost, and your plan.
 * A sold holding keeps one line; a failed read says prices still work.
 */
const Position = ({ symbol, pos, mine, status, sold, price, onReload, onDetails }) => {
  const [allLots, setAllLots] = useState(false);
  const thesis = mine?.thesis;
  const stop = thesis?.stop;
  const lots = mine?.lots || [];
  const held = mine?.position;
  const v = mine?.verdict;
  const first = v?.reasons?.[0];
  const fact = first && reasonFact(first, v.facts, v.limits);
  // One buy that is the whole position: its qty, price and gain are the stats above, so only its term and tax show.
  const oneLot = lots.length === 1 && pos && Math.abs(lots[0].qty - pos.qty) < 1e-9 ? lots[0] : null;
  const risk = {
    dist: stop != null && price ? (price - stop) / price : null,
    pnl: stop != null && pos ? (stop - pos.avg) * pos.qty : null,
    fromNow: stop != null && pos && price != null ? (stop - price) * pos.qty : null,
  };
  if (!pos && !sold && status !== 'error') return null;
  return (
    <Card className="mb-3">
      {pos && (
        <div>
          <p className="mb-2 text-[13px] text-[var(--text-muted)]">Your position · your broker account</p>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat label="Quantity · avg" value={`${formatQuantity(pos.qty)} · ${px(pos.avg)}`} />
            <Stat label="P&L" value={`${inr(pos.pnl, { sign: true })}${pos.pnlPct != null ? ` (${pct(pos.pnlPct, { sign: true, dp: 1 })})` : ''}`} valueClass={toneText(tone(pos.pnl))} />
            {pos.value != null && <Stat label="Value now" value={inr(pos.value)} />}
            {pos.weight != null && <Stat label="Of your portfolio" value={pct(pos.weight, { dp: 1 })} />}
            {held?.xirr != null && <Stat label={<Term id="xirr">Yearly (XIRR)</Term>} value={formatXirr(held.xirr)} valueClass={toneText(tone(held.xirr))} />}
            {held?.held_since && <Stat label="Held since" value={day(held.held_since)} />}
          </div>
          {stop != null && (
            <p className="mt-3 text-[14px] text-[var(--text)]" data-testid="stop-line">
              Stop <span className="private">{px(stop)}</span>
              {risk.dist != null && (risk.dist > 0 ? ` · ${pct(risk.dist, { dp: 1 })} below price` : ' · price is at or below your stop')}
              {' · if hit: '}
              {risk.fromNow != null && <span className="private">{inr(risk.fromNow, { sign: true })} from now </span>}
              <span className="private">({inr(risk.pnl, { sign: true })} vs what you paid)</span>
            </p>
          )}

          {v?.current && (
            // The verdict lives here, once: badge, since, its first reason with the figure, and the way to every reason.
            <div className="mt-4 pt-3 border-t border-[var(--border)]">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-semibold text-[var(--text-muted)]">Our verdict</span>
                <Badge kind={verdictKind(v.current)}>{verdictLabel(v.current)}</Badge>
                {v.since && <span className="text-[13px] text-[var(--text-muted)]">since {day(v.since)}</span>}
              </div>
              {first && <p className="mt-1.5 text-[14px] font-medium text-[var(--text)]">{REASONS[first] || first.replace(/_/g, ' ')}</p>}
              {fact && <p className="private text-[13px] tabular-nums text-[var(--text-muted)]">{fact}</p>}
              <button type="button" onClick={onDetails}
                className={`-mb-2 inline-flex min-h-11 items-center gap-0.5 text-[14px] font-semibold text-[var(--accent)] rounded-[12px] ${ring}`}>
                Why{v.reasons?.length > 1 ? `: ${v.reasons.length} reasons` : ''}<ChevronRight className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          )}

          {oneLot && (
            <p className="mt-3 text-[13px] tabular-nums">
              <span className={oneLot.days_to_long > 0 ? 'text-[var(--warn)]' : 'text-[var(--text-muted)]'}>{lotTerm(oneLot)}</span>
              {oneLot.est_tax > 0 && <span className="private text-[var(--text-muted)]"> · tax if sold ≈ {inr(oneLot.est_tax)}</span>}
            </p>
          )}
          {lots.length > 0 && !oneLot && (
            <div className="mt-4 pt-3 border-t border-[var(--border)]">
              <p className="text-[13px] font-semibold text-[var(--text-muted)]">Your lots{mine?.unknown_qty > 0 && <span className="font-normal"> · {formatQuantity(mine.unknown_qty)} shares with no buy on record</span>}</p>
              <ul>{(allLots ? lots : lots.slice(0, LOTS_SHOWN)).map((l) => <Lot key={`${l.buy_date}-${l.price}-${l.qty}`} l={l} />)}</ul>
              {lots.length > LOTS_SHOWN && (
                <button type="button" aria-expanded={allLots} onClick={() => setAllLots((v) => !v)}
                  className={`mt-1 inline-flex min-h-11 items-center gap-1 text-[14px] font-semibold text-[var(--accent)] rounded-[12px] ${ring}`}>
                  {allLots ? 'Fewer lots' : `All ${lots.length} lots`}
                  <ChevronDown className={`w-4 h-4 transition-transform ${allLots ? 'rotate-180' : ''}`} aria-hidden="true" />
                </button>
              )}
            </div>
          )}

          <div className="mt-4 pt-3 border-t border-[var(--border)]">
            <p className="mb-1.5 text-[13px] font-semibold text-[var(--text-muted)]">Your plan</p>
            <Plan symbol={symbol} thesis={thesis} onSaved={onReload} />
          </div>
        </div>
      )}
      {sold && <p className="text-[14px] text-[var(--text-muted)]">You no longer hold this. Past trades are on the chart.</p>}
      {status === 'error' && <ErrorLine message="Could not load your position from your broker account. Prices and charts still work." onRetry={onReload} />}
    </Card>
  );
};

export default Position;
