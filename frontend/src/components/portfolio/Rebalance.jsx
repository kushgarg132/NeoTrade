import React, { useEffect, useState } from 'react';
import { Loader2, Scale } from 'lucide-react';
import { Sheet, Statement, Row, Cell, Empty, Field, Scrip } from '../doc/Doc';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { TicketButton } from '../trading/OrderTicket';
import api, { endpoints, getPreferences } from '../../utils/api';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { ticketFrom, executeAll } from '../../utils/ticket';
import RebalanceAfter from './RebalanceAfter';
import { cn } from '../../utils/cn';

/**
 * The rebalance helper: targets from a rule (equal weight, or caps per stock
 * and sector) with per-stock overrides, optional new money, and names brought
 * in from the watchlist or the AI's longterm picks. Each trade opens a
 * pre-filled ticket the user confirms -- nothing is placed from here.
 */

const DEFAULTS = { rule: 'cap', max_stock_pct: 15, max_sector_pct: 30, overrides: {} };

const NumberField = ({ label, value, onChange, suffix, placeholder }) => (
  <label className="block min-w-0">
    <span className="field-label block mb-1">{label}</span>
    <span className="flex items-baseline gap-1 border-b border-[var(--border)]">
      <input
        type="number"
        inputMode="decimal"
        min="0"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-transparent figure-md text-sm py-1 outline-none"
      />
      {suffix && <span className="doc-meta">{suffix}</span>}
    </span>
  </label>
);

const tradeLabel = (t) => `${t.side} ${t.quantity}`;

const Tax = ({ tax }) => {
  if (!tax) return <span className="doc-meta">—</span>;
  if (tax.est_tax == null) return <span className="doc-meta normal-case">unknown</span>;
  return (
    <span className="figure-md text-sm">
      {formatCurrency(tax.est_tax)}
      {tax.unknown_qty > 0 && <span className="block doc-meta normal-case">{tax.unknown_qty} undated</span>}
    </span>
  );
};

const Rebalance = ({ snapshot, onTrade }) => {
  const [targets, setTargets] = useState(DEFAULTS);
  const [newMoney, setNewMoney] = useState('');
  const [candidates, setCandidates] = useState([]);
  const [ticked, setTicked] = useState([]);
  const [result, setResult] = useState(null);
  const [armed, setArmed] = useState(false); // first tap on Execute all; the second places the orders
  const [run, setRun] = useState(null); // per-order results while / after executing all
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let stale = false;
    Promise.allSettled([getPreferences(), api.get(endpoints.portfolio.candidates)]).then(([prefs, cands]) => {
      if (stale) return;
      const list = cands.status === 'fulfilled' ? cands.value.data || [] : [];
      setCandidates(list);
      const saved = prefs.status === 'fulfilled' ? prefs.value.data?.rebalance_targets : null;
      if (saved) setTargets({ ...DEFAULTS, ...saved });
      // A saved conviction rule starts with the AI's picks ticked.
      if (saved?.rule === 'conviction') setTicked(list.filter((c) => c.preselect).map((c) => c.symbol));
    });
    return () => { stale = true; };
  }, []);

  const stocks = (snapshot?.holdings || []).filter((r) => r.kind !== 'MF');
  const setOverride = (symbol, value) =>
    setTargets((t) => {
      const overrides = { ...t.overrides };
      if (value === '' || Number(value) <= 0) delete overrides[symbol];
      else overrides[symbol] = Number(value);
      return { ...t, overrides };
    });
  const chooseRule = (rule) => {
    setTargets((t) => ({ ...t, rule }));
    if (rule === 'conviction') setTicked(candidates.filter((c) => c.preselect).map((c) => c.symbol));
  };
  const toggle = (symbol) => setTicked((list) => (list.includes(symbol) ? list.filter((s) => s !== symbol) : [...list, symbol]));

  const calculate = async () => {
    setBusy(true);
    setError(null);
    const clean = { ...targets, max_stock_pct: Number(targets.max_stock_pct), max_sector_pct: Number(targets.max_sector_pct) };
    try {
      await api.put(endpoints.settings.preferences, { rebalance_targets: clean });
      const res = await api.post(endpoints.portfolio.rebalance, { new_money: Number(newMoney) || 0, candidates: ticked });
      setResult(res.data);
      setArmed(false);
      setRun(null);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Those targets could not be used: caps must be above 0 and at most 100, and overrides add up to 100% or less.');
    } finally {
      setBusy(false);
    }
  };

  const trade = (t) => onTrade && onTrade(ticketFrom({ symbol: t.symbol, suggested: t }));
  const trades = result?.trades || [];
  // Tax is the whole plan's, netted on the server: a sell at a loss lowers the total.
  const tax = result?.tax || { est_tax: 0, short_gain: 0, long_gain: 0, undated: 0 };
  const chargesTotal = trades.reduce((sum, t) => sum + (t.charges || 0), 0);
  const running = run?.some((r) => r.status === 'running');
  const execute = async () => {
    setArmed(false);
    const ordered = [...trades].sort((a, b) => (a.side === 'SELL' ? 0 : 1) - (b.side === 'SELL' ? 0 : 1));
    setRun(ordered.map((t, i) => ({ symbol: t.symbol, side: t.side, quantity: t.quantity, status: i === 0 ? 'running' : 'skipped', note: null })));
    const step = (out) => {
      const next = out.findIndex((r) => r.status === 'skipped');
      const stopped = out.some((r) => r.status === 'failed' || r.status === 'unknown');
      setRun(out.map((r, i) => (i === next && !stopped ? { ...r, status: 'running' } : r)));
    };
    setRun(await executeAll(trades, api.post, endpoints, step));
  };
  const RUN_TONE = { done: 'text-up', failed: 'text-down', unknown: 'text-down', running: 'text-[var(--accent)]', skipped: 'doc-meta' };
  const RUN_LABEL = { done: 'Placed', failed: 'Not placed', unknown: 'Unknown', running: 'Placing…', skipped: 'Not tried' };
  const gain = (x) => <span className={x < 0 ? 'text-down' : undefined}>{x < 0 ? `${formatCurrency(-x)} loss` : formatCurrency(x)}</span>;

  return (
    <div className="space-y-3 sm:space-y-4">
      <Sheet
        title="Rebalance"
        meta="targets you set"
        actions={
          <Button variant="primary" size="sm" onClick={calculate} disabled={busy}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Scale className="w-3.5 h-3.5" />}
            {busy ? 'Calculating' : 'Calculate'}
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex" role="radiogroup" aria-label="Target rule">
            {[
              { id: 'cap', label: 'Caps' },
              { id: 'equal', label: 'Equal weight' },
              ...(snapshot?.verdicts_visible ? [{ id: 'conviction', label: 'Conviction' }] : []),
            ].map((option) => (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={targets.rule === option.id}
                onClick={() => chooseRule(option.id)}
                className={cn(
                  'min-h-11 sm:min-h-0 px-3 py-1.5 text-sm border border-[var(--border)] -ml-px first:ml-0',
                  targets.rule === option.id ? 'bg-[var(--text)] text-[var(--surface)]' : 'text-[var(--text-muted)]'
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {targets.rule !== 'equal' && (
              <>
                <NumberField label="Max per stock" suffix="%" value={targets.max_stock_pct}
                  onChange={(v) => setTargets((t) => ({ ...t, max_stock_pct: v }))} />
                <NumberField label="Max per sector" suffix="%" value={targets.max_sector_pct}
                  onChange={(v) => setTargets((t) => ({ ...t, max_sector_pct: v }))} />
              </>
            )}
            <NumberField label="Add new money" suffix="₹" value={newMoney} placeholder="0" onChange={setNewMoney} />
          </div>
          <p className="doc-meta normal-case">
            New money buys what is under target first; sells cover only what is still over it.
            {targets.rule === 'cap' ? ' Caps keep your current weights and trim only what is above them.' : ''}
            {targets.rule === 'conviction'
              ? ' Conviction weights each stock by its review score: ADD gets more, SELL is sold. New names are the AI\'s top picks.'
              : ''}
          </p>

          {stocks.length > 0 && (
            <details>
              <summary className="field-label cursor-pointer min-h-11 sm:min-h-0 flex items-center">
                Fix a stock's target ({Object.keys(targets.overrides).length} set)
              </summary>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
                {stocks.map((row) => (
                  <NumberField key={row.symbol} label={row.symbol} suffix="%" placeholder="rule"
                    value={targets.overrides[row.symbol] ?? ''} onChange={(v) => setOverride(row.symbol, v)} />
                ))}
              </div>
            </details>
          )}

          {candidates.length > 0 && (
            <div>
              <p className="field-label mb-1">Bring in new names</p>
              <ul className="flex flex-wrap gap-2">
                {candidates.map((c) => (
                  <li key={c.symbol}>
                    <label className="inline-flex items-center gap-2 min-h-11 sm:min-h-0 px-2 py-1 border border-[var(--border)] cursor-pointer">
                      <input type="checkbox" checked={ticked.includes(c.symbol)} onChange={() => toggle(c.symbol)} />
                      <span className="figure-md text-sm">{c.symbol}</span>
                      <Badge variant="secondary">
                        {c.source === 'ai' ? `AI pick${c.score != null ? ` · ${c.score.toFixed(2)}` : ''}` : 'Watchlist'}
                      </Badge>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm text-[var(--loss)] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2">
              {error}
            </p>
          )}
          {!onTrade && <p className="doc-meta normal-case">Switch to My account to trade from here.</p>}
        </div>
      </Sheet>

      {result && (
        <Sheet title="Trades" meta={`${trades.length} · cash left ${formatCurrency(result.cash_left)}`}>
          {result.uninvested_pct > 0.5 && (
            <p role="status" className="mb-2 text-sm border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2">
              Your caps leave {formatPercent(result.uninvested_pct)} of the book uninvested: there are not enough
              stocks or sectors to fill them. Raise the caps or use Equal weight to stay invested.
            </p>
          )}
          {result.stale_since && <p className="doc-meta normal-case pb-2">Prices from the last close: log in to your broker for live ones.</p>}
          {trades.length === 0 ? (
            <Empty title="Nothing to do" detail="Your holdings are already close to their targets." />
          ) : (
            <>
              <div className="mb-3 grid grid-cols-3 gap-3 rounded-[12px] bg-[var(--surface-2)] px-3 py-2" aria-label="Total cost of these trades">
                <Field label="Total tax est." value={formatCurrency(tax.est_tax)} tone={tax.est_tax > 0 ? 'down' : undefined} />
                <Field label="Charges" value={formatCurrency(chargesTotal)} />
                <Field label="Total cost" value={formatCurrency(tax.est_tax + chargesTotal)} />
                <p className="col-span-3 doc-meta normal-case">
                  Net short-term: {gain(tax.short_gain)} · long-term: {gain(tax.long_gain)}. Losses on sells are set off against gains first.
                  {tax.undated > 0 && ` ${tax.undated} sell${tax.undated > 1 ? 's' : ''} not fully dated in your journal: real tax may differ.`}
                </p>
              </div>
              {armed ? (
                <div className="mb-3 border border-[var(--border)] px-3 py-3">
                  <p className="text-sm font-semibold mb-3">Your portfolio after these trades</p>
                  <RebalanceAfter after={result.after} />
                </div>
              ) : result.after?.rows?.length > 0 && (
                <details className="mb-3 border border-[var(--border)] px-3">
                  <summary className="cursor-pointer min-h-11 flex items-center text-sm font-semibold">See portfolio after these trades</summary>
                  <div className="pb-3"><RebalanceAfter after={result.after} /></div>
                </details>
              )}
              {onTrade && !run && (armed ? (
                <div role="alert" className="mb-3 border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2 space-y-2">
                  <p className="text-sm">
                    Check the portfolio above. Places {trades.length} real order{trades.length > 1 ? 's' : ''} on your broker: sells first, then buys, each a
                    limit order at the plan price. Stops at the first order that fails.
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    <Button variant="secondary" onClick={() => setArmed(false)}>Cancel</Button>
                    <Button variant="danger" onClick={execute}>Real money. Execute all</Button>
                  </div>
                </div>
              ) : (
                <Button variant="primary" className="mb-3 w-full" onClick={() => setArmed(true)}>Review & execute all {trades.length} trades</Button>
              ))}
              {run && (
                <div className="mb-3 border border-[var(--border)] px-3 py-2" role="status" aria-live="polite">
                  <ul className="divide-y divide-[var(--border)]">
                    {run.map((r) => (
                      <li key={`${r.symbol}-${r.side}`} className="py-1.5 flex items-baseline justify-between gap-3 text-sm">
                        <span className="figure-md">{r.side} {r.quantity} {r.symbol}</span>
                        <span className={cn('text-right', RUN_TONE[r.status])}>
                          {r.status === 'running' && <Loader2 className="inline w-3.5 h-3.5 mr-1 animate-spin" />}
                          {RUN_LABEL[r.status]}
                          {r.note && r.status !== 'done' && <span className="block doc-meta normal-case">{r.note}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {!running && (
                    <p className="mt-2 doc-meta normal-case">
                      {run.every((r) => r.status === 'done') ? 'All orders placed. Check Journal for fills.' : 'Stopped. Orders marked Placed went through; recalculate before trying the rest.'}
                    </p>
                  )}
                </div>
              )}
              <ul className="sm:hidden divide-y divide-[var(--border)]">
                {trades.map((t) => (
                  <li key={`${t.symbol}-${t.side}`} className="py-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="figure-md text-sm">{t.symbol}</span>
                      {onTrade && <TicketButton label={tradeLabel(t)} tone={t.side === 'SELL' ? 'loss' : 'gain'} onClick={() => trade(t)} />}
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-3">
                      <Field label="Value" value={formatCurrency(t.value)} />
                      <Field label="Weight" value={`${formatPercent(t.weight_now)} → ${formatPercent(t.weight_after)}`} />
                      <Field label="Tax est." value={t.side === 'SELL' ? (t.tax?.est_tax == null ? 'unknown' : formatCurrency(t.tax.est_tax)) : '—'} />
                    </div>
                  </li>
                ))}
              </ul>
              <div className="hidden sm:block">
                <Statement
                  columns={[
                    { key: 'scrip', label: 'Scrip' },
                    { key: 'side', label: 'Trade' },
                    { key: 'value', label: 'Value', align: 'right' },
                    { key: 'weight', label: 'Weight now → after', align: 'right' },
                    { key: 'tax', label: 'Tax est.', align: 'right' },
                    { key: 'go', label: '', align: 'right' },
                  ]}
                >
                  {trades.map((t) => (
                    <Row key={`${t.symbol}-${t.side}`}>
                      <Cell><Scrip symbol={t.symbol} /></Cell>
                      <Cell mono className={t.side === 'SELL' ? 'text-down' : 'text-up'}>{tradeLabel(t)}</Cell>
                      <Cell align="right" mono>{formatCurrency(t.value)}</Cell>
                      <Cell align="right" mono>{formatPercent(t.weight_now)} → {formatPercent(t.weight_after)}</Cell>
                      <Cell align="right"><Tax tax={t.tax} /></Cell>
                      <Cell align="right">
                        {onTrade && <TicketButton label="Trade" tone={t.side === 'SELL' ? 'loss' : 'gain'} onClick={() => trade(t)} />}
                      </Cell>
                    </Row>
                  ))}
                </Statement>
              </div>
            </>
          )}
          {[...(result.skipped || []), ...(result.excluded || [])].length > 0 && (
            <ul className="mt-3 doc-meta normal-case space-y-0.5">
              {[...(result.skipped || []), ...(result.excluded || [])].map((s) => (
                <li key={`${s.symbol}-${s.reason}`}>{s.symbol}: {s.reason}</li>
              ))}
            </ul>
          )}
          <p className="mt-3 doc-meta normal-case">
            Tax is an estimate before the ₹1.25L long-term exemption. Each trade opens a ticket for you to confirm.
          </p>
        </Sheet>
      )}
    </div>
  );
};

export default Rebalance;
