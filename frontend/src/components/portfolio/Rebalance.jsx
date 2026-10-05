import React, { useEffect, useState } from 'react';
import { Loader2, Scale } from 'lucide-react';
import { Sheet, Statement, Row, Cell, Empty, Field, Scrip } from '../doc/Doc';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { TicketButton } from '../trading/OrderTicket';
import api, { endpoints } from '../../utils/api';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { ticketFrom } from '../../utils/ticket';
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
    <span className="flex items-baseline gap-1 border-b border-[var(--rule-strong)]">
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let stale = false;
    api.get(endpoints.settings.preferences)
      .then((res) => !stale && res.data?.rebalance_targets && setTargets({ ...DEFAULTS, ...res.data.rebalance_targets }))
      .catch(() => {});
    api.get(endpoints.portfolio.candidates)
      .then((res) => !stale && setCandidates(res.data || []))
      .catch(() => {});
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
  const toggle = (symbol) => setTicked((list) => (list.includes(symbol) ? list.filter((s) => s !== symbol) : [...list, symbol]));

  const calculate = async () => {
    setBusy(true);
    setError(null);
    const clean = { ...targets, max_stock_pct: Number(targets.max_stock_pct), max_sector_pct: Number(targets.max_sector_pct) };
    try {
      await api.put(endpoints.settings.preferences, { rebalance_targets: clean });
      const res = await api.post(endpoints.portfolio.rebalance, { new_money: Number(newMoney) || 0, candidates: ticked });
      setResult(res.data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Those targets could not be used: caps must be above 0 and at most 100, and overrides add up to 100% or less.');
    } finally {
      setBusy(false);
    }
  };

  const trade = (t) => onTrade && onTrade(ticketFrom({ symbol: t.symbol, suggested: t }));
  const trades = result?.trades || [];

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
            ].map((option) => (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={targets.rule === option.id}
                onClick={() => setTargets((t) => ({ ...t, rule: option.id }))}
                className={cn(
                  'min-h-11 sm:min-h-0 px-3 py-1.5 text-sm border border-[var(--rule-strong)] -ml-px first:ml-0',
                  targets.rule === option.id ? 'bg-[var(--ink)] text-[var(--paper)]' : 'text-[var(--ink-soft)]'
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {targets.rule === 'cap' && (
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
                    <label className="inline-flex items-center gap-2 min-h-11 sm:min-h-0 px-2 py-1 border border-[var(--rule-strong)] cursor-pointer">
                      <input type="checkbox" checked={ticked.includes(c.symbol)} onChange={() => toggle(c.symbol)} />
                      <span className="figure-md text-sm">{c.symbol}</span>
                      <Badge variant="secondary">{c.source === 'ai' ? 'AI pick' : 'Watchlist'}</Badge>
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
              <ul className="sm:hidden divide-y divide-[var(--rule)]">
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
