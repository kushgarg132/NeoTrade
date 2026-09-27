import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, RefreshCw } from 'lucide-react';
import Layout from '../components/Layout';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine, Scrip } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { formatCurrency, formatQuantity, formatPercent, formatDateTime } from '../utils/formatters';

/**
 * Real money: the user's long-term holdings across every connected broker,
 * and how they are doing. Facts only — how much, how concentrated, against
 * NIFTY. It does not yet say what to do about any of it.
 */

const BUTTON =
  'inline-flex items-center gap-2 px-3 py-1.5 min-h-9 border border-[var(--rule-strong)] font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] text-[var(--ink-soft)] hover:text-[var(--ink)] hover:border-[var(--ink)] transition-colors disabled:opacity-50';

const BROKER = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };

const Line = ({ label, children }) => (
  <div className="flex items-baseline justify-between gap-4 py-1.5">
    <span className="text-sm text-[var(--ink-soft)]">{label}</span>
    <span className="figure-md text-sm tabular-nums text-right">{children}</span>
  </div>
);

const Benchmark = ({ benchmark }) => {
  if (!benchmark.covered_pct) {
    return (
      <p className="doc-meta normal-case pt-3">
        No NIFTY comparison yet: it needs the dates you bought, from your trade history.{' '}
        <Link to="/journal" className="text-[var(--stamp)] underline">
          Import it in Journal
        </Link>
        .
      </p>
    );
  }
  return (
    <div className="pt-3">
      <Line label="Your holdings">
        <Money value={benchmark.portfolio_pct} percent />
      </Line>
      <Line label="NIFTY 50, same money, same days">
        <Money value={benchmark.nifty_pct} percent />
      </Line>
      <p className="doc-meta normal-case pt-1">
        Covers the {formatPercent(benchmark.covered_pct)} of your money whose buy dates your journal knows.
      </p>
    </div>
  );
};

const Concentration = ({ concentration, count }) => (
  <Sheet title="How spread out">
    <Line label="Largest holding">
      {concentration.top_symbol} · {formatPercent(concentration.top_pct)}
    </Line>
    <Line label="Top five together">{formatPercent(concentration.top5_pct)}</Line>
    {concentration.effective_holdings && (
      <p className="doc-meta normal-case py-1.5">
        Your {count} holdings are weighted like {concentration.effective_holdings.toFixed(1)} equal ones.
      </p>
    )}
    <p className="field-label mt-3 mb-2">By sector</p>
    <ul className="space-y-2">
      {concentration.sectors.map((sector) => (
        <li key={sector.sector}>
          <div className="flex justify-between text-sm">
            <span className="text-[var(--ink-soft)]">{sector.sector}</span>
            <span className="figure-md">{formatPercent(sector.pct)}</span>
          </div>
          <div className="h-1.5 bg-[var(--paper-sunk)] mt-1" aria-hidden="true">
            <div className="h-full bg-[var(--ink)]" style={{ width: `${Math.min(sector.pct, 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
    {concentration.correlated.length > 0 && (
      <>
        <p className="field-label mt-4 mb-1">Move together</p>
        <ul>
          {concentration.correlated.map((pair) => (
            <li key={`${pair.a}-${pair.b}`} className="text-sm py-1 text-[var(--ink-soft)]">
              {pair.a} and {pair.b} — {pair.correlation.toFixed(2)} correlation over a year, closer to one
              bet than two
            </li>
          ))}
        </ul>
      </>
    )}
  </Sheet>
);

const HoldingsTable = ({ rows }) => (
  <Statement
    columns={[
      { key: 'scrip', label: 'Holding' },
      { key: 'qty', label: 'Qty', align: 'right' },
      { key: 'avg', label: 'Avg cost', align: 'right' },
      { key: 'value', label: 'Value', align: 'right' },
      { key: 'pnl', label: 'P&L', align: 'right' },
      { key: 'nifty', label: 'NIFTY same days', align: 'right' },
    ]}
  >
    {rows.map((row) => (
      <Row key={row.isin || row.symbol}>
        <Cell>
          {row.kind === 'MF' ? (
            <span className="text-sm">{row.name || row.symbol}</span>
          ) : (
            <Scrip symbol={row.symbol} />
          )}
          <span className="block doc-meta normal-case">
            {row.sector || (row.kind === 'STOCK' ? '' : row.kind)}
            {row.weight_pct != null && ` · ${formatPercent(row.weight_pct)} of portfolio`}
          </span>
        </Cell>
        <Cell align="right" mono>
          {formatQuantity(row.quantity)}
        </Cell>
        <Cell align="right" mono>
          {formatCurrency(row.avg_price)}
        </Cell>
        <Cell align="right" mono>
          {row.value != null ? formatCurrency(row.value) : '—'}
        </Cell>
        <Cell align="right">
          <Money value={row.pnl} />
          {row.pnl_pct != null && (
            <span className="block">
              <Money value={row.pnl_pct} percent size="sm" />
            </span>
          )}
        </Cell>
        <Cell align="right">
          {row.nifty_pnl_pct != null ? <Money value={row.nifty_pnl_pct} percent /> : <span className="doc-meta">—</span>}
        </Cell>
      </Row>
    ))}
  </Statement>
);

const MyPortfolio = () => {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);

  useEffect(() => {
    api
      .get(endpoints.portfolio.get)
      .then((res) => setSnapshot(res.data))
      .catch(() => setSnapshot(null))
      .finally(() => setLoading(false));
  }, []);

  const refresh = async () => {
    setBusy(true);
    setFailure(null);
    try {
      const res = await api.post(endpoints.portfolio.refresh);
      setSnapshot(res.data);
    } catch (err) {
      setFailure(err?.response?.data?.detail || 'Could not read your holdings');
    } finally {
      setBusy(false);
    }
  };

  const action = (
    <button type="button" className={BUTTON} onClick={refresh} disabled={busy}>
      {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
      {busy ? 'Reading brokers' : 'Analyse now'}
    </button>
  );

  const stocks = snapshot?.holdings.filter((row) => row.kind === 'STOCK') || [];
  const funds = snapshot?.holdings.filter((row) => row.kind !== 'STOCK') || [];
  const brokers = (snapshot?.brokers || []).map((b) => BROKER[b] || b).join(', ');

  return (
    <Layout>
      <div className="space-y-4">
        <Sheet
          title="Portfolio"
          meta={snapshot ? `${formatDateTime(snapshot.at)}${brokers ? ` · ${brokers}` : ''}` : null}
          actions={action}
        >
          {failure && (
            <p className="mb-3 text-sm text-[var(--loss)] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2">
              {failure}
            </p>
          )}
          {Object.entries(snapshot?.errors || {}).map(([broker, message]) => (
            <p key={broker} className="mb-2 doc-meta normal-case text-[var(--loss)]">
              {BROKER[broker] || broker} could not be read: {message}. Reconnect it in Settings.
            </p>
          ))}
          {loading ? (
            <Ruling rows={4} />
          ) : !snapshot ? (
            <Empty
              title="Your holdings, from your own broker"
              detail="Reads long-term holdings from every connected broker — Kite, Upstox, Angel One — and shows how they are doing against NIFTY."
            />
          ) : (
            <>
              <Line label="Invested">{formatCurrency(snapshot.totals.invested)}</Line>
              <Line label="Gain">
                <Money value={snapshot.totals.pnl} />{' '}
                <Money value={snapshot.totals.pnl_pct} percent size="sm" />
              </Line>
              <Line label="Today">
                <Money value={snapshot.totals.day_change} />
              </Line>
              <NetLine label="Current value">
                <span className="figure-lg">{formatCurrency(snapshot.totals.value)}</span>
              </NetLine>
              <Benchmark benchmark={snapshot.benchmark} />
              {snapshot.totals.unpriced.length > 0 && (
                <p className="doc-meta normal-case pt-2">
                  No price from your broker for {snapshot.totals.unpriced.join(', ')}; left out of the totals.
                </p>
              )}
            </>
          )}
        </Sheet>

        {snapshot && snapshot.holdings.length > 0 && (
          <>
            <Concentration concentration={snapshot.concentration} count={snapshot.totals.count} />
            {stocks.length > 0 && (
              <Sheet title="Stocks" meta={`${stocks.length}`}>
                <HoldingsTable rows={stocks} />
              </Sheet>
            )}
            {funds.length > 0 && (
              <Sheet title="Funds & ETFs" meta={`${funds.length}`}>
                <HoldingsTable rows={funds} />
              </Sheet>
            )}
          </>
        )}
      </div>
    </Layout>
  );
};

export default MyPortfolio;
