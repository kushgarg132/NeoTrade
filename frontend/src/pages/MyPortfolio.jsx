import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, RefreshCw } from 'lucide-react';
import Layout from '../components/Layout';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine, Scrip, Stamp } from '../components/doc/Doc';
import Markdown from '../components/common/Markdown';
import api, { endpoints } from '../utils/api';
import { formatCurrency, formatQuantity, formatPercent, formatDateTime } from '../utils/formatters';

/**
 * Real money: the user's long-term holdings across every connected broker,
 * how they are doing, and a verdict on each from plain rules (scored by the
 * same conviction formula as everything else; the AI only explains). Until
 * the deployment allows it, only admins see SELL / HOLD / ADD — everyone
 * else sees the same facts, with serious holdings marked "Review first".
 */

const BUTTON =
  'inline-flex items-center gap-2 px-3 py-1.5 min-h-9 border border-[var(--rule-strong)] font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] text-[var(--ink-soft)] hover:text-[var(--ink)] hover:border-[var(--ink)] transition-colors disabled:opacity-50';

const BROKER = { kite: 'Kite', upstox: 'Upstox', angel_one: 'Angel One' };

const REASONS = {
  loss_beyond_limit: 'Further below its cost than your loss limit',
  earnings_falling_3q: 'Profit fell in each of the last three quarters',
  earnings_rising_3q: 'Profit rose in each of the last three quarters',
  below_200dma: 'Price is under its 200-day average',
  uptrend: 'Price above its 50-day average, which is above its 200-day',
  overweight: 'A bigger share of your portfolio than your size limit',
  high_debt: 'Debt is more than twice equity',
  strong_roe: 'Return on equity of 15% or more',
  reasonable_valuation: 'Price to earnings under 40',
};

const TONE = { SELL: 'loss', REVIEW: 'loss', ADD: 'gain' };
const LABEL = { REVIEW: 'Review first' };
// Most urgent first.
const ORDER = { SELL: 0, REVIEW: 1, HOLD: 2, ADD: 3, KEEP: 4 };

const Verdict = ({ row }) =>
  row.verdict ? (
    <span className="inline-flex flex-col items-end gap-1">
      <Stamp label={LABEL[row.verdict] || row.verdict} tone={TONE[row.verdict] || 'stamp'} />
      {row.previous_verdict && row.previous_verdict !== row.verdict && (
        <span className="doc-meta normal-case">was {LABEL[row.previous_verdict] || row.previous_verdict}</span>
      )}
    </span>
  ) : null;

const figure = (value, suffix = '') => (value == null ? '—' : `${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}${suffix}`);

const Detail = ({ row }) => {
  const health = row.health || {};
  const trend = health.trend || {};
  const fundamentals = health.fundamentals || {};
  return (
    <div className="py-3 space-y-3 text-sm">
      {row.note && <p className="text-[var(--ink)] leading-relaxed">{row.note}</p>}
      {row.reason_codes?.length > 0 && (
        <ul className="space-y-1">
          {row.reason_codes.map((code) => (
            <li key={code} className="text-[var(--ink-soft)]">
              · {REASONS[code] || code.replace(/_/g, ' ')}
            </li>
          ))}
        </ul>
      )}
      {row.score && (
        <p className="doc-meta normal-case">
          Conviction {row.score.final.toFixed(2)} · rules {row.score.rule.toFixed(2)}, news weighted to 0.30 at most
        </p>
      )}
      {row.kind === 'STOCK' && (
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2">
          {[
            ['Price', figure(trend.close)],
            ['50-day avg', figure(trend.sma_50)],
            ['200-day avg', figure(trend.sma_200)],
            ['Below 52w high', figure(trend.below_high_pct, '%')],
            ['3-month move', figure(trend.return_3m_pct, '%')],
            ['P/E', figure(fundamentals.pe)],
            ['ROE', fundamentals.roe == null ? '—' : figure(fundamentals.roe * 100, '%')],
            ['Debt / equity', figure(fundamentals.debt_to_equity, '×')],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="field-label">{label}</dt>
              <dd className="figure-md">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {health.headlines?.length > 0 && (
        <ul className="space-y-1">
          {health.headlines.map((headline) => (
            <li key={headline.url}>
              <a href={headline.url} target="_blank" rel="noreferrer" className="text-[var(--stamp)] hover:underline">
                {headline.title}
              </a>
              <span className="doc-meta normal-case"> · {headline.source}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

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

const HoldingsTable = ({ rows, open, onToggle }) => (
  <Statement
    columns={[
      { key: 'verdict', label: 'Review', align: 'right' },
      { key: 'scrip', label: 'Holding' },
      { key: 'qty', label: 'Qty', align: 'right' },
      { key: 'avg', label: 'Avg cost', align: 'right' },
      { key: 'value', label: 'Value', align: 'right' },
      { key: 'pnl', label: 'P&L', align: 'right' },
      { key: 'nifty', label: 'NIFTY same days', align: 'right' },
    ]}
  >
    {rows.map((row) => (
      <React.Fragment key={row.isin || row.symbol}>
      <Row
        className="cursor-pointer hover:bg-[var(--paper-sunk)]"
        onClick={() => onToggle(row.isin || row.symbol)}
        aria-expanded={open === (row.isin || row.symbol)}
      >
        <Cell align="right">
          <Verdict row={row} />
        </Cell>
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
      {open === (row.isin || row.symbol) && (
        <tr>
          <td colSpan={7}>
            <Detail row={row} />
          </td>
        </tr>
      )}
      </React.Fragment>
    ))}
  </Statement>
);

const MyPortfolio = () => {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);
  const [open, setOpen] = useState(null);
  const toggle = (key) => setOpen((current) => (current === key ? null : key));

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
      {busy ? 'Reviewing, this takes a minute' : 'Analyse now'}
    </button>
  );

  const urgency = (row) => ORDER[row.verdict] ?? 5;
  const byUrgency = [...(snapshot?.holdings || [])].sort((a, b) => urgency(a) - urgency(b));
  const stocks = byUrgency.filter((row) => row.kind === 'STOCK');
  const funds = byUrgency.filter((row) => row.kind !== 'STOCK');
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
              {snapshot.stale_since && (
                <p className="doc-meta normal-case pt-2">
                  No broker was connected: holdings as of {formatDateTime(snapshot.stale_since)}, repriced from the
                  latest closes. Log in to your broker to refresh them.
                </p>
              )}
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
            {snapshot.summary && (
              <Sheet title="Review" meta="AI write-up of the figures below">
                <div className="text-sm leading-relaxed">
                  <Markdown>{snapshot.summary}</Markdown>
                </div>
              </Sheet>
            )}
            {snapshot.plan && (
              <Sheet title="Action plan" meta="AI suggestions from the figures and the app's own scan">
                <div className="text-sm leading-relaxed">
                  <Markdown>{snapshot.plan}</Markdown>
                </div>
              </Sheet>
            )}
            <Concentration concentration={snapshot.concentration} count={snapshot.totals.count} />
            {stocks.length > 0 && (
              <Sheet title="Stocks" meta={`${stocks.length} · tap one for its reasons`}>
                {!snapshot.verdicts_visible && (
                  <p className="doc-meta normal-case pb-2">
                    Holdings marked Review first have serious results on the review rules. What to do is your call.
                  </p>
                )}
                <HoldingsTable rows={stocks} open={open} onToggle={toggle} />
              </Sheet>
            )}
            {funds.length > 0 && (
              <Sheet title="Funds & ETFs" meta={`${funds.length}`}>
                <HoldingsTable rows={funds} open={open} onToggle={toggle} />
              </Sheet>
            )}
          </>
        )}
      </div>
    </Layout>
  );
};

export default MyPortfolio;
