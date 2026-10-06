import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw, Loader2 } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import { Sheet, Field, Empty, Ruling } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import api, { endpoints } from '../utils/api';
import { formatLevel, formatCompactNumber, formatNoteDate, marketPhase } from '../utils/formatters';
import { cn } from '../utils/cn';

/**
 * Live option chain for NIFTY 50 and BANK NIFTY, from the user's own Upstox
 * session. Calls on the left, puts on the right, strikes down the middle,
 * centred on the strike nearest spot. In-the-money sides are shaded, the way
 * a broker's chain reads, so the spot line is visible without a number.
 * Read-only: nothing here places an order.
 */

const UNDERLYINGS = [
  { id: 'NIFTY', label: 'NIFTY 50' },
  { id: 'BANKNIFTY', label: 'Bank Nifty' },
];
const AROUND_ATM = 10;

const oi = (leg) => (leg?.oi == null ? '—' : formatCompactNumber(leg.oi));
const oiChange = (leg) =>
  leg?.oi_change ? `${leg.oi_change > 0 ? '+' : '−'}${formatCompactNumber(Math.abs(leg.oi_change))}` : '';
const premium = (leg) => (leg?.ltp == null ? '—' : formatLevel(leg.ltp));

// Upstox reports 0 or a capped 500%+ when it cannot solve for IV (deep in the
// money, no trades, expiry day): those are not volatilities, so print nothing.
const ivShown = (iv) => iv != null && iv > 0 && iv < 300;

const OptionChain = () => {
  const [params, setParams] = useSearchParams();
  const underlying = UNDERLYINGS.some((u) => u.id === params.get('u')) ? params.get('u') : 'NIFTY';
  const [expiries, setExpiries] = useState(null);
  const [expiry, setExpiry] = useState(null);
  const [chain, setChain] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get(endpoints.options.expiries(underlying))
      .then((res) => {
        if (cancelled) return;
        setExpiries(res.data);
        setExpiry(res.data[0] || null);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err?.response?.data?.detail || 'Could not load expiries'));
    return () => {
      cancelled = true;
    };
  }, [underlying]);

  const loadChain = (which = expiry) => {
    if (!which) return;
    setBusy(true);
    api
      .get(endpoints.options.chain(underlying, which))
      .then((res) => {
        setChain(res.data);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the chain'))
      .finally(() => setBusy(false));
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => loadChain(expiry), [expiry]);

  const rows = useMemo(() => {
    if (!chain) return [];
    if (all || chain.atm_strike == null) return chain.strikes;
    const at = chain.strikes.findIndex((row) => row.strike === chain.atm_strike);
    return chain.strikes.slice(Math.max(0, at - AROUND_ATM), at + AROUND_ATM + 1);
  }, [chain, all]);

  const pickUnderlying = (id) => {
    setChain(null);
    setExpiries(null);
    setParams({ u: id });
  };

  return (
    <Layout>
      <div className="space-y-4">
        <SectionTabs tabs={RESEARCH_TABS} label="Research" />
        <Sheet
          title="Option chain"
          meta={marketPhase() === 'open' ? 'Live · Upstox' : 'Market closed · last prices · Upstox'}
          actions={
            <Button variant="secondary" size="sm" onClick={() => loadChain()} disabled={busy || !expiry}>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Refresh
            </Button>
          }
          bodyClassName="p-0"
        >
          <div className="grid grid-cols-2 border-b border-[var(--rule-strong)]" role="tablist" aria-label="Underlying">
            {UNDERLYINGS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={underlying === item.id}
                onClick={() => pickUnderlying(item.id)}
                className={cn(
                  'min-h-11 px-4 font-[family-name:var(--font-narrow)] text-xs font-semibold uppercase tracking-[0.11em] border-b-2 -mb-px transition-colors',
                  underlying === item.id
                    ? 'border-[var(--stamp)] text-[var(--ink)]'
                    : 'border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)]'
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          {expiries && expiries.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 bg-[var(--paper-sunk)]">
              <label className="flex items-center gap-2">
                <span className="field-label">Expiry</span>
                <select
                  value={expiry || ''}
                  onChange={(event) => setExpiry(event.target.value)}
                  className="bg-[var(--paper)] border border-[var(--rule-strong)] px-2 py-1 figure-md text-sm"
                >
                  {expiries.map((date) => (
                    <option key={date} value={date}>
                      {formatNoteDate(new Date(`${date}T00:00:00+05:30`))}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                onClick={() => setAll((value) => !value)}
                className="field-label text-[var(--stamp)] hover:underline"
              >
                {all ? `Near the money only` : 'All strikes'}
              </button>
            </div>
          )}
        </Sheet>

        {error ? (
          <Sheet>
            <Empty
              title="No option chain"
              detail={error}
              action={
                <Link to="/settings" className="field-label text-[var(--stamp)] hover:underline">
                  Broker settings
                </Link>
              }
            />
          </Sheet>
        ) : !chain ? (
          <Sheet>
            <Ruling rows={8} />
          </Sheet>
        ) : (
          <Sheet title={chain.name} meta={formatNoteDate(new Date(`${chain.expiry}T00:00:00+05:30`))} bodyClassName="p-0">
            <div className="grid grid-cols-3 gap-4 px-4 py-3 border-b border-[var(--rule)]">
              <Field label="Spot" value={formatLevel(chain.spot)} />
              <Field label="At the money" value={chain.atm_strike == null ? '—' : formatLevel(chain.atm_strike)} />
              <Field label="Put / call OI" value={chain.pcr == null ? '—' : chain.pcr.toFixed(2)} />
            </div>

            <table className="w-full text-sm border-collapse table-fixed">
              <thead>
                <tr className="border-b border-[var(--rule-strong)]">
                  <th className="field-label py-2 px-2 text-left" scope="col" aria-label="Call open interest">OI</th>
                  <th className="field-label py-2 px-2 text-right" scope="col">Call</th>
                  <th className="field-label py-2 px-2 text-center bg-[var(--paper-sunk)]" scope="col">Strike</th>
                  <th className="field-label py-2 px-2 text-left" scope="col">Put</th>
                  <th className="field-label py-2 px-2 text-right" scope="col" aria-label="Put open interest">OI</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const callItm = chain.spot != null && row.strike < chain.spot;
                  const putItm = chain.spot != null && row.strike > chain.spot;
                  const atm = row.strike === chain.atm_strike;
                  return (
                    <tr
                      key={row.strike}
                      className={cn(
                        'border-b border-[var(--rule)]',
                        atm && 'border-y-2 border-y-[var(--stamp)]'
                      )}
                    >
                      <td className={cn('py-2 px-2 align-top', callItm && 'bg-[var(--stamp-soft)]')}>
                        <span className="figure-md block">{oi(row.call)}</span>
                        <span className={cn('doc-meta normal-case', row.call?.oi_change > 0 ? 'text-up' : 'text-down')}>
                          {oiChange(row.call)}
                        </span>
                      </td>
                      <td className={cn('py-2 px-2 text-right align-top', callItm && 'bg-[var(--stamp-soft)]')}>
                        <span className="figure-md whitespace-nowrap">{premium(row.call)}</span>
                        {ivShown(row.call?.iv) && <span className="block doc-meta normal-case whitespace-nowrap text-[0.625rem]">IV {row.call.iv.toFixed(1)}</span>}
                      </td>
                      <td className="py-2 px-1 text-center align-top bg-[var(--paper-sunk)]">
                        <span className={cn('figure-md whitespace-nowrap', atm && 'text-[var(--stamp)]')}>
                          {Math.round(row.strike).toLocaleString('en-IN')}
                        </span>
                      </td>
                      <td className={cn('py-2 px-2 align-top', putItm && 'bg-[var(--stamp-soft)]')}>
                        <span className="figure-md whitespace-nowrap">{premium(row.put)}</span>
                        {ivShown(row.put?.iv) && <span className="block doc-meta normal-case whitespace-nowrap text-[0.625rem]">IV {row.put.iv.toFixed(1)}</span>}
                      </td>
                      <td className={cn('py-2 px-2 text-right align-top', putItm && 'bg-[var(--stamp-soft)]')}>
                        <span className="figure-md block">{oi(row.put)}</span>
                        <span className={cn('doc-meta normal-case', row.put?.oi_change > 0 ? 'text-up' : 'text-down')}>
                          {oiChange(row.put)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="px-4 py-3 doc-meta normal-case">
              OI: open interest. Shaded: in the money. OI change is since the previous session. Prices refresh when you tap
              Refresh. Market data only, not advice.
            </p>
          </Sheet>
        )}
      </div>
    </Layout>
  );
};

export default OptionChain;
