import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RefreshCw, Loader2 } from 'lucide-react';
import SettingsPage from './SettingsPage';
import Card from '../components/ui/Card';
import Tabs from '../components/ui/Tabs';
import Skeleton from '../components/ui/Skeleton';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
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
const AROUND_ATM = 8;
const clock = (d) => d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' });

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
  const [fetchedAt, setFetchedAt] = useState(null);

  const loadExpiries = () =>
    api
      .get(endpoints.options.expiries(underlying))
      .then((res) => {
        setExpiries(res.data ?? []);
        setExpiry(res.data?.[0] || null);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load expiries'));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadExpiries(); }, [underlying]);

  const loadChain = (which = expiry) => {
    if (!which) return;
    setBusy(true);
    api
      .get(endpoints.options.chain(underlying, which))
      .then((res) => {
        setChain(res.data);
        setFetchedAt(new Date());
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

  const retry = () => (expiry ? loadChain() : loadExpiries());
  const stat = (label, value, big) => (
    <div className="min-w-0">
      <p className="text-[12px] text-[var(--text-muted)]">{label}</p>
      <p className={cn('figure-md tabular-nums', big ? 'text-[20px] font-bold' : 'text-[16px]')}>{value}</p>
    </div>
  );

  return (
    <SettingsPage title="Option chain" back="/settings/lab" backLabel="Lab"
      right={
            <Button variant="secondary" size="sm" onClick={() => loadChain()} disabled={busy || !expiry} aria-busy={busy} className="min-h-11">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              Refresh
            </Button>
      }
    >
      <div className="space-y-4">
        <Card>
          <p className="text-[13px] text-[var(--text-muted)] mb-3">
            {marketPhase() === 'open' ? 'Live · Upstox' : 'Market closed · last prices · Upstox'}
            {fetchedAt && ` · Fetched ${clock(fetchedAt)} IST`}
          </p>
          <Tabs tabs={UNDERLYINGS.map((u) => ({ id: u.id, label: u.label }))} value={underlying} onChange={pickUnderlying} label="Underlying" />

          {expiries && expiries.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 mt-3">
              <label className="flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
                Expiry
                <select
                  value={expiry || ''}
                  onChange={(event) => setExpiry(event.target.value)}
                  className="min-h-11 rounded-[8px] bg-[var(--surface)] border border-[var(--border)] px-2 figure-md text-[14px]"
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
                className="min-h-11 px-2 text-[14px] font-semibold text-[var(--accent)]"
              >
                {all ? 'Near the money only' : 'All strikes'}
              </button>
            </div>
          )}
        </Card>

        {error ? (
          <Card>
            <ErrorLine message={`Couldn’t load the ${underlying === 'NIFTY' ? 'NIFTY 50' : 'Bank Nifty'} chain. ${error}`} onRetry={retry} />
            <Link to="/settings" className="inline-flex items-center min-h-11 text-[14px] font-semibold text-[var(--accent)]">Check broker settings</Link>
          </Card>
        ) : expiries && expiries.length === 0 ? (
          <Empty
            title="No expiries listed"
            body="The chain needs your Upstox connection."
            action={<Link to="/settings" className="inline-flex items-center min-h-11 px-3 font-semibold text-[var(--accent)]">Connect Upstox</Link>}
          />
        ) : !chain ? (
          <Card><Skeleton rows={8} /></Card>
        ) : (
          <section className="rounded-[16px] border border-[var(--border)] bg-[var(--surface)] py-4 overflow-hidden">
            <div className="flex items-center justify-between gap-3 px-4 mb-3">
              <h2 className="text-[15px] font-semibold">{chain.name}</h2>
              <span className="text-[13px] text-[var(--text-muted)]">{formatNoteDate(new Date(`${chain.expiry}T00:00:00+05:30`))}</span>
            </div>
            <div className="grid grid-cols-3 gap-3 px-4 pb-3 border-b border-[var(--border)]">
              {stat('Spot', formatLevel(chain.spot), true)}
              {stat('At the money', chain.atm_strike == null ? '—' : formatLevel(chain.atm_strike))}
              {stat('PCR (put/call OI)', chain.pcr == null ? '—' : chain.pcr.toFixed(2))}
            </div>

            <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-[14px] border-collapse table-fixed">
              <thead>
                <tr className="border-b border-[var(--border)] text-[12px] text-[var(--text-muted)]">
                  <th className="py-2 px-2 text-left font-medium" scope="col" aria-label="Call open interest">OI</th>
                  <th className="py-2 px-2 text-right font-medium" scope="col">Call</th>
                  <th className="py-2 px-2 text-center font-medium bg-[var(--surface-2)]" scope="col">Strike</th>
                  <th className="py-2 px-2 text-left font-medium" scope="col">Put</th>
                  <th className="py-2 px-2 text-right font-medium" scope="col" aria-label="Put open interest">OI</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const callItm = chain.spot != null && row.strike < chain.spot;
                  const putItm = chain.spot != null && row.strike > chain.spot;
                  const atm = row.strike === chain.atm_strike;
                  return (
                    <tr key={row.strike} className={cn('border-b border-[var(--border)]', atm && 'border-y-2 border-y-[var(--accent)]')}>
                      <td className={cn('py-1.5 px-2 align-top', callItm && 'bg-[var(--accent-soft)]')}>
                        <span className="figure-md block">{oi(row.call)}</span>
                        <span className={cn('text-[12px]', row.call?.oi_change > 0 ? 'text-up' : 'text-down')}>{oiChange(row.call)}</span>
                      </td>
                      <td className={cn('py-1.5 px-2 text-right align-top', callItm && 'bg-[var(--accent-soft)]')}>
                        <span className="figure-md whitespace-nowrap">{premium(row.call)}</span>
                        {ivShown(row.call?.iv) && <span className="block text-[12px] text-[var(--text-muted)] whitespace-nowrap">IV {row.call.iv.toFixed(1)}</span>}
                      </td>
                      <td className="py-1.5 px-1 text-center align-top bg-[var(--surface-2)]">
                        <span className={cn('figure-md whitespace-nowrap', atm && 'text-[var(--accent)] font-bold')}>
                          {Math.round(row.strike).toLocaleString('en-IN')}
                        </span>
                        {atm && <span className="block text-[12px] font-semibold text-[var(--accent)]">ATM</span>}
                      </td>
                      <td className={cn('py-1.5 px-2 align-top', putItm && 'bg-[var(--accent-soft)]')}>
                        <span className="figure-md whitespace-nowrap">{premium(row.put)}</span>
                        {ivShown(row.put?.iv) && <span className="block text-[12px] text-[var(--text-muted)] whitespace-nowrap">IV {row.put.iv.toFixed(1)}</span>}
                      </td>
                      <td className={cn('py-1.5 px-2 text-right align-top', putItm && 'bg-[var(--accent-soft)]')}>
                        <span className="figure-md block">{oi(row.put)}</span>
                        <span className={cn('text-[12px]', row.put?.oi_change > 0 ? 'text-up' : 'text-down')}>{oiChange(row.put)}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
            <p className="px-4 pt-3 text-[13px] text-[var(--text-muted)]">
              OI: open interest. IV: implied volatility. ATM: strike nearest spot. Shaded: in the money. OI change is since the
              previous session. Prices refresh when you tap Refresh. Market data only, not advice.
            </p>
          </section>
        )}
      </div>
    </SettingsPage>
  );
};

export default OptionChain;
