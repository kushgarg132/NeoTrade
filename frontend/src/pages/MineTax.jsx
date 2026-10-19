import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { PORTFOLIO_TABS } from '../components/layout/sections';
import { Sheet, Money, Empty, Ruling, Scrip } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { formatCurrency, formatQuantity } from '../utils/formatters';
import { taxYears } from '../utils/mine';

const EXEMPTION = 125000;
const fyLabel = (fy) => `FY ${fy}-${String((fy + 1) % 100).padStart(2, '0')}`;
const currentFy = () => {
  const d = new Date();
  return d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
};
const BUTTON = 'min-h-11 px-4 border border-[var(--ink)] font-[family-name:var(--font-narrow)] text-xs font-semibold uppercase tracking-[0.11em] disabled:opacity-50';
const day = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: '2-digit', timeZone: 'UTC' });

const Line = ({ symbol, detail, children }) => (
  <li className="flex items-center justify-between gap-3 py-1.5 border-b border-[var(--rule)]">
    <div className="min-w-0">
      <Scrip symbol={symbol} />
      {detail && <p className="doc-meta normal-case">{detail}</p>}
    </div>
    <div className="text-right shrink-0">{children}</div>
  </li>
);
const None = ({ text }) => <p className="text-sm text-[var(--ink-faint)]">{text}</p>;

const MineTax = () => {
  const [fy, setFy] = useState(() => taxYears(currentFy())[0]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setData(null);
    api
      .get(endpoints.mine.tax(fy))
      .then((res) => (setData(res.data), setError(null)))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load tax'));
  }, [fy]);
  useEffect(load, [load]);

  const importHistory = () => {
    setBusy(true);
    api
      .post(endpoints.journal.importUpstox, { days: 730 })
      .then(load)
      .catch((err) => setError(err?.response?.data?.detail || 'Import failed'))
      .finally(() => setBusy(false));
  };

  const select = (
    <select aria-label="Financial year" value={fy} onChange={(e) => setFy(Number(e.target.value))} className="min-h-9 border border-[var(--rule-strong)] bg-transparent px-2 text-sm">
      {taxYears(currentFy()).map((y) => <option key={y} value={y}>{fyLabel(y)}</option>)}
    </select>
  );

  let body;
  if (error) body = <Sheet title="Tax"><Empty title="Could not load" detail={error} /></Sheet>;
  else if (!data) body = <Sheet title="Tax"><Ruling rows={4} /></Sheet>;
  else if (!data.has_history) {
    body = (
      <Sheet title="Tax">
        <Empty
          title="Import your trades to see tax"
          detail="Tax is worked out from your trades, so it needs them first: a Zerodha Console tradebook CSV, or your Upstox history."
          action={
            <span className="flex flex-wrap justify-center gap-2">
              <Link to="/import" className={`${BUTTON} inline-flex items-center`}>Import a tradebook</Link>
              <button type="button" className={BUTTON} onClick={importHistory} disabled={busy}>{busy ? 'Importing…' : 'Import Upstox history'}</button>
            </span>
          }
        />
      </Sheet>
    );
  } else {
    const { realised: r, unrealised, turning_long: turning, harvest, unknown, pre_2018: pre } = data;
    const usedPct = Math.min(100, (r.exemption_used / EXEMPTION) * 100);
    body = (
      <>
        <Sheet title="Realised this FY" meta={fyLabel(fy)}>
          <dl className="grid grid-cols-3 gap-x-3">
            <div><dt className="field-label">Short-term</dt><dd><Money value={r.short_gain} size="sm" className="text-sm" /></dd></div>
            <div><dt className="field-label">Long-term</dt><dd><Money value={r.long_gain} size="sm" className="text-sm" /></dd></div>
            <div><dt className="field-label">Est. tax</dt><dd className="figure-md text-sm">{formatCurrency(r.est_tax)}</dd></div>
          </dl>
          <div className="mt-3">
            <p className="doc-meta normal-case">
              Long-term exemption: {formatCurrency(r.exemption_used)} used, {formatCurrency(r.exemption_left)} left of {formatCurrency(EXEMPTION)}
            </p>
            <div className="h-2 mt-1 border border-[var(--rule-strong)]" role="img" aria-label={`${Math.round(usedPct)}% of exemption used`}>
              <div className="h-full bg-[var(--ink)]" style={{ width: `${usedPct}%` }} />
            </div>
          </div>
          <p className="doc-meta normal-case mt-2">Charges paid: {formatCurrency(r.charges)}</p>
          {r.uncertain?.length > 0 && (
            <p className="doc-meta normal-case mt-2">
              May be matched to the wrong buy (older shares the journal never saw): {r.uncertain.join(', ')}.
            </p>
          )}
        </Sheet>

        <Sheet title="Unrealised by lot">
          {unrealised.length === 0 ? <None text="No open lots." /> : (
            <ul>
              {unrealised.map((u, i) => (
                <Line key={i} symbol={u.symbol} detail={`${formatQuantity(u.qty)} @ ${formatCurrency(u.price)} · bought ${day(u.buy_date)} · ${u.term}-term`}>
                  <Money value={u.gain} size="sm" className="text-sm" />
                </Line>
              ))}
            </ul>
          )}
          {unknown.length > 0 && (
            <p className="doc-meta normal-case mt-2">
              Cannot date: {unknown.map((u) => `${u.symbol} (${formatQuantity(u.qty)}${u.sold ? ' sold, no buy found' : ''})`).join(', ')}. Left out of the figures; import your history to fix.
            </p>
          )}
          {pre.length > 0 && (
            <p className="doc-meta normal-case mt-2">Bought before 1 Feb 2018, grandfathered cost not applied: {pre.join(', ')}.</p>
          )}
        </Sheet>

        <Sheet title="Turning long-term soon">
          {turning.length === 0 ? <None text="Nothing crosses 365 days in the next 60 days." /> : (
            <ul>
              {turning.map((t, i) => (
                <Line key={i} symbol={t.symbol} detail={`${formatQuantity(t.qty)} · gain ${formatCurrency(t.gain)}`}>
                  <p className="text-sm">Wait {t.days} {t.days === 1 ? 'day' : 'days'}</p>
                  <p className="doc-meta normal-case">save {formatCurrency(t.saving)}</p>
                </Line>
              ))}
            </ul>
          )}
        </Sheet>

        <Sheet title="Before 31 March">
          <p className="field-label mb-1">Loss harvest</p>
          {harvest.loss.length === 0 ? <None text="No holdings at a loss." /> : (
            <ul>
              {harvest.loss.map((h) => (
                <Line key={h.symbol} symbol={h.symbol} detail={`${formatQuantity(h.qty)} · loss ${formatCurrency(-h.loss)}`}>
                  <p className="text-sm">saves {formatCurrency(h.saving)}</p>
                </Line>
              ))}
            </ul>
          )}
          <p className="field-label mt-4 mb-1">Gain harvest</p>
          {harvest.gain.length === 0 ? <None text="No long-term gains fit the unused exemption." /> : (
            <ul>
              {harvest.gain.map((h) => (
                <Line key={h.symbol} symbol={h.symbol} detail={`sell ${formatQuantity(h.qty)} to book ${formatCurrency(h.gain)} tax-free, then rebuy`} />
              ))}
            </ul>
          )}
        </Sheet>
      </>
    );
  }

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4">
        <SectionTabs tabs={PORTFOLIO_TABS} label="Portfolio" />
        <div className="flex justify-end">{select}</div>
        {body}
        <p className="doc-meta normal-case">Estimate, not tax advice. Not covered: pre-2018 grandfathered cost, F&amp;O and intraday income, set-off against other income.</p>
      </div>
    </Layout>
  );
};

export default MineTax;
