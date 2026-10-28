import React, { useCallback, useEffect, useState } from 'react';
import Card from '../ui/Card';
import Stat from '../ui/Stat';
import Button from '../ui/Button';
import ListRow from '../ui/ListRow';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';
import { inr, tone } from '../ui/format';
import api, { endpoints } from '../../utils/api';
import { formatQuantity } from '../../utils/formatters';
import { taxYears } from '../../utils/mine';
import { fyStart } from '../../utils/months';
import { stockPath } from '../../utils/stocks';
import useSymbolNews from '../../hooks/useSymbolNews';
import { lossCause } from '../../utils/news';

const EXEMPTION = 125000;
const fyLabel = (fy) => `FY ${fy}-${String((fy + 1) % 100).padStart(2, '0')}`;
const currentFy = fyStart;
const day = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: '2-digit', timeZone: 'UTC' });
const Note = ({ children }) => <p className="text-[13px] text-[var(--text-muted)] mt-2">{children}</p>;
const None = ({ text }) => <p className="text-[14px] text-[var(--text-muted)]">{text}</p>;

/** A loss-harvest line: size of the loss, then whether fresh bad news is behind it (lossCause). */
const LossSub = ({ h, entry }) => {
  const cause = lossCause(entry);
  return (
    <>
      <span className="block truncate">{`${formatQuantity(h.qty)} · loss ${inr(h.loss)}`}</span>
      <span className={`block truncate ${cause.news ? 'text-[var(--loss)]' : ''}`} title={cause.text}>{cause.text}</span>
    </>
  );
};

/** Tax estimate for a financial year: GET /mine/tax. */
const TaxTab = ({ onImport }) => {
  const [fy, setFy] = useState(() => taxYears(currentFy())[0]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const { news } = useSymbolNews((data?.harvest?.loss || []).map((h) => h.symbol));

  const load = useCallback(() => {
    api
      .get(endpoints.mine.tax(fy))
      .then((res) => (setData(res.data), setError(null)))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load tax.'));
  }, [fy]);
  useEffect(load, [load]);

  const importHistory = () => {
    setBusy(true);
    api
      .post(endpoints.journal.importUpstox, { days: 730 })
      .then(load)
      .catch((err) => setError(err?.response?.data?.detail || 'Import failed.'))
      .finally(() => setBusy(false));
  };

  const select = (
    <select
      aria-label="Financial year" value={fy} onChange={(e) => { setData(null); setFy(Number(e.target.value)); }}
      className="min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 text-[15px] text-[var(--text)]"
    >
      {taxYears(currentFy()).map((y) => <option key={y} value={y}>{fyLabel(y)}</option>)}
    </select>
  );

  let body;
  if (error) body = <Card title="Tax"><ErrorLine message={error} onRetry={() => { setError(null); load(); }} /></Card>;
  else if (!data) body = <Card title="Tax"><Skeleton rows={4} /></Card>;
  else if (!data.has_history) {
    body = (
      <Empty
        title="Import your trades to see tax"
        body="Tax is worked out from your trades: a Zerodha Console tradebook CSV, or your Upstox history."
        action={
          <span className="flex flex-wrap justify-center gap-2">
            <Button onClick={onImport}>Import a tradebook</Button>
            <Button variant="secondary" onClick={importHistory} disabled={busy}>{busy ? 'Importing…' : 'Import Upstox history'}</Button>
          </span>
        }
      />
    );
  } else {
    const { realised: r, unrealised, turning_long: turning, harvest, unknown, pre_2018: pre } = data;
    const usedPct = Math.min(100, (r.exemption_used / EXEMPTION) * 100);
    body = (
      <>
        <Card title="Realised this year">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Short-term" value={inr(r.short_gain, { sign: true })} tone={tone(r.short_gain)} />
            <Stat label="Long-term" value={inr(r.long_gain, { sign: true })} tone={tone(r.long_gain)} />
            <Stat label="Est. tax" value={inr(r.est_tax)} />
          </div>
          <div className="mt-4">
            <p className="private text-[13px] text-[var(--text-muted)]">
              Long-term exemption: {inr(r.exemption_used)} used, {inr(r.exemption_left)} left of {inr(EXEMPTION)}
            </p>
            <div className="h-2 mt-1 rounded-full bg-[var(--surface-2)] overflow-hidden" role="img" aria-label={`${Math.round(usedPct)}% of exemption used`}>
              <div className="h-full bg-[var(--accent)]" style={{ width: `${usedPct}%` }} />
            </div>
          </div>
          <Note>Charges paid: <span className="private">{inr(r.charges)}</span></Note>
          {r.uncertain?.length > 0 && (
            <Note>May be matched to the wrong buy (older shares the journal never saw): {r.uncertain.join(', ')}.</Note>
          )}
        </Card>

        <Card title="Unrealised by lot">
          {unrealised.length === 0 ? <None text="No open lots." /> : unrealised.map((u, i) => (
            <ListRow
              key={i} to={stockPath(u.symbol)} title={u.symbol}
              sub={`${formatQuantity(u.qty)} @ ${inr(u.price)} · bought ${day(u.buy_date)} · ${u.term}-term`}
              right={inr(u.gain, { sign: true })} rightTone={tone(u.gain)}
            />
          ))}
          {unknown.length > 0 && (
            <Note>Cannot date: {unknown.map((u) => `${u.symbol} (${formatQuantity(u.qty)}${u.sold ? ' sold, no buy found' : ''})`).join(', ')}. Left out of the figures; import your history to fix.</Note>
          )}
          {pre.length > 0 && <Note>Bought before 1 Feb 2018, grandfathered cost not applied: {pre.join(', ')}.</Note>}
        </Card>

        <Card title="Turning long-term soon">
          {turning.length === 0 ? <None text="Nothing crosses 365 days in the next 60 days." /> : turning.map((t, i) => (
            <ListRow
              key={i} to={stockPath(t.symbol)} title={t.symbol}
              sub={`${formatQuantity(t.qty)} · gain ${inr(t.gain)}`}
              right={`Wait ${t.days} ${t.days === 1 ? 'day' : 'days'}, save ${inr(t.saving)}`}
            />
          ))}
        </Card>

        <Card title="Before 31 March">
          <p className="text-[13px] font-semibold text-[var(--text-muted)] mb-1">Loss harvest</p>
          {harvest.loss.length === 0 ? <None text="No holdings at a loss." /> : harvest.loss.map((h) => (
            <ListRow
              key={h.symbol} to={stockPath(h.symbol)} title={h.symbol} right={`saves ${inr(h.saving)}`} rightTone="gain"
              sub={<LossSub h={h} entry={news[h.symbol.toUpperCase()]} />}
            />
          ))}
          {harvest.loss.length > 0 && <Note>Whether material bad news in the last 72 hours is behind the loss. Context only.</Note>}
          <p className="text-[13px] font-semibold text-[var(--text-muted)] mt-4 mb-1">Gain harvest</p>
          {harvest.gain.length === 0 ? <None text="No long-term gains fit the unused exemption." /> : harvest.gain.map((h) => (
            <ListRow key={h.symbol} to={stockPath(h.symbol)} title={h.symbol} sub={`sell ${formatQuantity(h.qty)} to book ${inr(h.gain)} tax-free, then rebuy`} />
          ))}
        </Card>
      </>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">{select}</div>
      {body}
      <p className="text-[13px] text-[var(--text-muted)]">Estimate, not tax advice. Not covered: pre-2018 grandfathered cost, F&amp;O and intraday income, set-off against other income.</p>
    </div>
  );
};

export default TaxTab;
