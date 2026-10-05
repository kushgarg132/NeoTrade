import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, RefreshCw, ChevronDown } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { MINE_TABS } from '../components/layout/sections';
import { AccountSwitch } from '../components/common/AccountSwitch';
import { useAccount } from '../hooks/useAccount';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, Scrip, Stamp, Tabs } from '../components/doc/Doc';
import { useTab } from '../hooks/useTab';
import Markdown from '../components/common/Markdown';
import { cn } from '../utils/cn';
import OrderTicket, { TicketButton } from '../components/trading/OrderTicket';
import api, { endpoints } from '../utils/api';
import { ticketFrom } from '../utils/ticket';
import Rebalance from '../components/portfolio/Rebalance';
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

const Verdict = ({ row, compact = false }) =>
  row.verdict ? (
    <span className="inline-flex flex-col items-end gap-1">
      <Stamp
        label={LABEL[row.verdict] || row.verdict}
        tone={TONE[row.verdict] || 'stamp'}
        className={compact ? 'px-1.5 py-0.5 text-[0.5625rem] tracking-[0.12em]' : undefined}
      />
      {!compact && row.previous_verdict && row.previous_verdict !== row.verdict && (
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
      <p className="doc-meta normal-case">
        No NIFTY comparison yet: it needs your buy dates.{' '}
        <Link to="/mine/trades" className="text-[var(--stamp)] underline">
          Import them in Journal
        </Link>
        .
      </p>
    );
  }
  return (
    <p className="text-sm text-[var(--ink-soft)]">
      Against NIFTY, same money, same days: you <Money value={benchmark.portfolio_pct} percent size="sm" className="text-sm" />
      {' · '}NIFTY <Money value={benchmark.nifty_pct} percent size="sm" className="text-sm" />
      <span className="doc-meta normal-case"> · covers {formatPercent(benchmark.covered_pct)}</span>
    </p>
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
    <ul className="space-y-1.5">
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

/**
 * The action plan folded by its `### ` headings (Improve the mix, Sell or
 * trim, Add): the first group open, the rest one tap away. A plan without
 * headings is clamped with Show all instead.
 */
const PlanGroups = ({ plan }) => {
  const groups = plan
    .split(/^### /m)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      const [title, ...rest] = chunk.split('\n');
      const body = rest.join('\n').trim();
      return { title: title.trim(), body, count: (body.match(/^\s*[-*] /gm) || []).length };
    });
  const [open, setOpen] = useState(0);
  const [all, setAll] = useState(false);

  if (!/^### /m.test(plan)) {
    return (
      <div>
        <div className={cn('text-sm leading-relaxed', !all && 'line-clamp-[12]')}>
          <Markdown>{plan}</Markdown>
        </div>
        <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all} className="mt-2 field-label text-[var(--stamp)] hover:underline min-h-11 sm:min-h-0">
          {all ? 'Show less' : 'Show all'}
        </button>
      </div>
    );
  }
  return (
    <div className="divide-y divide-[var(--rule)]">
      {groups.map((group, i) => (
        <div key={group.title}>
          <button
            type="button"
            onClick={() => setOpen((current) => (current === i ? null : i))}
            aria-expanded={open === i}
            className="w-full flex items-center justify-between gap-3 py-2.5 text-left min-h-11"
          >
            <span className="field-label">{group.title}</span>
            <span className="inline-flex items-center gap-2 doc-meta">
              {group.count > 0 && group.count}
              <ChevronDown className={cn('w-4 h-4 transition-transform', open === i && 'rotate-180')} aria-hidden="true" />
            </span>
          </button>
          {open === i && (
            <div className="pb-3 text-sm leading-relaxed">
              <Markdown>{group.body}</Markdown>
            </div>
          )}
        </div>
      ))}
    </div>
  );
};

/** Sell or add to an equity holding from the user's own account. */
const TradeButtons = ({ row, onTrade }) =>
  onTrade && row.kind !== 'MF' ? (
    <span className="inline-flex gap-2">
      <TicketButton label="Sell" tone="loss" onClick={() => onTrade({ symbol: row.symbol, side: 'SELL', lastPrice: row.last_price })} />
      <TicketButton label="Add" onClick={() => onTrade({ symbol: row.symbol, lastPrice: row.last_price })} />
    </span>
  ) : null;

// The AI verdict as a one-tap trade: SELL sells the holding, ADD buys up to
// the rebalance target. It opens a pre-filled ticket; nothing is placed here.
const AiAction = ({ row, onTrade }) => {
  const ticket = onTrade ? ticketFrom(row) : null;
  if (ticket) {
    return (
      <TicketButton
        label={`${ticket.side} ${ticket.quantity} · ${formatCurrency(ticket.quantity * ticket.limitPrice)}`}
        tone={ticket.side === 'SELL' ? 'loss' : 'gain'}
        onClick={() => onTrade(ticket)}
      />
    );
  }
  if (row.suggested?.at_target) return <span className="doc-meta normal-case">at target</span>;
  if (row.suggested?.skipped) return <span className="doc-meta normal-case">{row.suggested.skipped}</span>;
  return null;
};

/**
 * A phone's holdings: one line each -- name and weight, value and gain, the
 * verdict -- with everything else a tap away. The full statement is for
 * wider sheets.
 */
const HoldingsList = ({ rows, open, onToggle, onTrade }) => (
  <ul className="sm:hidden -mx-3 divide-y divide-[var(--rule)]">
    {rows.map((row) => {
      const key = row.isin || row.symbol;
      return (
        <li key={key}>
          <button
            type="button"
            onClick={() => onToggle(key)}
            aria-expanded={open === key}
            className="w-full px-3 py-2.5 flex items-center gap-3 text-left hover:bg-[var(--paper-sunk)]"
          >
            <span className="min-w-0 flex-1">
              <span className="figure-md text-sm block truncate">{row.kind === 'MF' ? row.name || row.symbol : row.symbol}</span>
              <span className="doc-meta normal-case block truncate">
                {row.weight_pct != null ? `${formatPercent(row.weight_pct)}` : row.kind}
                {row.sector ? ` · ${row.sector}` : ''}
              </span>
            </span>
            <span className="text-right shrink-0">
              <span className="figure-md text-sm block">{row.value != null ? formatCurrency(row.value) : '—'}</span>
              <Money value={row.pnl_pct} percent size="sm" className="text-xs" />
            </span>
            <span className="w-[4.5rem] flex justify-end shrink-0">
              <Verdict row={row} compact />
            </span>
          </button>
          {onTrade && row.suggested && (
            <div className="px-3 pb-2 -mt-1 flex justify-end">
              <AiAction row={row} onTrade={onTrade} />
            </div>
          )}
          {open === key && (
            <div className="px-3 pb-3">
              <dl className="grid grid-cols-3 gap-2 pb-1 border-b border-[var(--rule)]">
                <div><dt className="field-label">Qty</dt><dd className="figure-md text-sm">{formatQuantity(row.quantity)}</dd></div>
                <div><dt className="field-label">Avg cost</dt><dd className="figure-md text-sm">{formatCurrency(row.avg_price)}</dd></div>
                <div><dt className="field-label">P&amp;L</dt><dd><Money value={row.pnl} size="sm" className="text-sm" /></dd></div>
              </dl>
              {row.kind !== 'MF' && (
                <p className="pt-2 flex items-center justify-between gap-3">
                  <Scrip symbol={row.symbol}>Open {row.symbol}'s enquiry</Scrip>
                  <TradeButtons row={row} onTrade={onTrade} />
                </p>
              )}
              <Detail row={row} />
            </div>
          )}
        </li>
      );
    })}
  </ul>
);

const HoldingsTable = ({ rows, open, onToggle, onTrade }) => (
  <div className="hidden sm:block">
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
          {onTrade && row.suggested && (
            <span className="block mt-1">
              <AiAction row={row} onTrade={onTrade} />
            </span>
          )}
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
            {onTrade && row.kind !== 'MF' && (
              <div className="px-3 pt-2 flex justify-end">
                <TradeButtons row={row} onTrade={onTrade} />
              </div>
            )}
            <Detail row={row} />
          </td>
        </tr>
      )}
      </React.Fragment>
    ))}
  </Statement>
  </div>
);

const Holdings = (props) => (
  <>
    <HoldingsList {...props} />
    <HoldingsTable {...props} />
  </>
);

const MyPortfolio = ({ lockedAccount = null }) => {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);
  const [open, setOpen] = useState(null);
  const [ticket, setTicket] = useState(null);
  const toggle = (key) => setOpen((current) => (current === key ? null : key));

  const accountState = useAccount(lockedAccount);
  const { account } = accountState;
  // `stale` is true once the account changed: a late reply for the old one is dropped.
  const loadSnapshot = (stale = () => false) =>
    api
      .get(endpoints.portfolio.get, { params: { account } })
      .then((res) => !stale() && setSnapshot(res.data))
      .catch(() => !stale() && setSnapshot(null))
      .finally(() => !stale() && setLoading(false));
  useEffect(() => {
    if (!account) return undefined;
    let gone = false;
    loadSnapshot(() => gone);
    return () => {
      gone = true;
    };
  }, [account]);

  const refresh = async () => {
    setBusy(true);
    setFailure(null);
    try {
      const res = await api.post(endpoints.portfolio.refresh);
      // The refresh returns every account; show the chosen one.
      if (account === 'all') setSnapshot(res.data);
      else await loadSnapshot();
    } catch (err) {
      setFailure(err?.response?.data?.detail || 'Could not read your holdings');
    } finally {
      setBusy(false);
    }
  };

  const action = (
    <button type="button" className={BUTTON} onClick={refresh} disabled={busy} aria-label="Analyse the portfolio now">
      {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
      <span className={busy ? '' : 'hidden sm:inline'}>{busy ? 'Reviewing…' : 'Analyse now'}</span>
    </button>
  );

  const urgency = (row) => ORDER[row.verdict] ?? 5;
  const byUrgency = [...(snapshot?.holdings || [])].sort((a, b) => urgency(a) - urgency(b));
  const stocks = byUrgency.filter((row) => row.kind === 'STOCK');
  const funds = byUrgency.filter((row) => row.kind !== 'STOCK');
  const brokers = (snapshot?.brokers || []).map((b) => BROKER[b] || b).join(', ');
  const hasHoldings = snapshot && snapshot.holdings.length > 0;

  const TABS = [
    { id: 'plan', label: 'Plan' },
    { id: 'holdings', label: `Holdings${hasHoldings ? ` · ${snapshot.holdings.length}` : ''}` },
    { id: 'rebalance', label: 'Rebalance' },
    { id: 'mix', label: 'Mix' },
    { id: 'review', label: 'Review' },
  ];
  const [tab, setTab] = useTab(TABS.map((t) => t.id));

  return (
    <Layout>
      <div className="private space-y-3 sm:space-y-4">
        {lockedAccount ? <SectionTabs tabs={MINE_TABS} label="My account" /> : <AccountSwitch {...accountState} />}
        {lockedAccount && accountState.roles && !accountState.hasRole && (
          <Link to="/settings?tab=accounts" className="flex items-center justify-between gap-3 sheet px-3 py-2.5 sm:px-4 border-dashed hover:bg-[var(--paper-sunk)]">
            <span className="text-sm">Showing every account. Set which broker is <span className="field-label">yours</span> in More → Accounts.</span>
            <span className="field-label text-[var(--stamp)]">Set ›</span>
          </Link>
        )}
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
            <Ruling rows={3} />
          ) : !snapshot ? (
            <Empty
              title="Your holdings, from your own broker"
              detail="Reads long-term holdings from every connected broker — Kite, Upstox, Angel One — and shows how they are doing against NIFTY."
            />
          ) : (
            <div className="space-y-3">
              <div className="flex items-end justify-between gap-3">
                <div className="min-w-0">
                  <p className="field-label mb-1">Current value</p>
                  <p className="figure-lg text-[clamp(1.75rem,8vw,2.5rem)]">{formatCurrency(snapshot.totals.value)}</p>
                </div>
              </div>
              <dl className="grid grid-cols-3 gap-2 pt-2 border-t border-[var(--rule)]">
                <div className="min-w-0">
                  <dt className="field-label mb-0.5">Invested</dt>
                  <dd className="figure-md text-sm truncate">{formatCurrency(snapshot.totals.invested)}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="field-label mb-0.5">Gain</dt>
                  <dd className="truncate"><Money value={snapshot.totals.pnl} size="sm" className="text-sm" /></dd>
                  <dd><Money value={snapshot.totals.pnl_pct} percent size="sm" className="text-xs" /></dd>
                </div>
                <div className="min-w-0">
                  <dt className="field-label mb-0.5">Today</dt>
                  <dd className="truncate"><Money value={snapshot.totals.day_change} size="sm" className="text-sm" /></dd>
                </div>
              </dl>
              <Benchmark benchmark={snapshot.benchmark} />
              {snapshot.stale_since && (
                <p className="doc-meta normal-case">
                  No broker connected: holdings as of {formatDateTime(snapshot.stale_since)}, repriced from the latest
                  closes. Log in to your broker to refresh them.
                </p>
              )}
              {snapshot.totals.unpriced.length > 0 && (
                <p className="doc-meta normal-case">
                  No price from your broker for {snapshot.totals.unpriced.join(', ')}; left out of the totals.
                </p>
              )}
            </div>
          )}
        </Sheet>

        {hasHoldings && (
          <div>
            <Tabs tabs={TABS} active={tab} onSelect={setTab} label="Portfolio sections" />
            <div className="pt-3 sm:pt-4">
              {tab === 'plan' &&
                (snapshot.plan ? (
                  <Sheet title="Action plan" meta="AI write-up">
                    <PlanGroups plan={snapshot.plan} />
                    <p className="doc-meta normal-case pt-3 mt-3 border-t border-[var(--rule)]">
                      Rules and an AI write-up, not a registered adviser's advice.
                    </p>
                  </Sheet>
                ) : (
                  <Sheet>
                    <Empty
                      title="No action plan yet"
                      detail={
                        snapshot.verdicts_visible
                          ? 'Analyse now to write one from your holdings and the latest scan.'
                          : 'The action plan is not available on this account.'
                      }
                      action={snapshot.verdicts_visible ? action : null}
                    />
                  </Sheet>
                ))}

              {tab === 'holdings' && (
                <div className="space-y-3 sm:space-y-4">
                  {stocks.length > 0 && (
                    <Sheet title="Stocks" meta={`${stocks.length} · tap for reasons`}>
                      {!snapshot.verdicts_visible && (
                        <p className="doc-meta normal-case pb-2">
                          Holdings marked Review first have serious results on the review rules. What to do is your call.
                        </p>
                      )}
                      <Holdings rows={stocks} open={open} onToggle={toggle} onTrade={account === 'mine' ? setTicket : null} />
                    </Sheet>
                  )}
                  {funds.length > 0 && (
                    <Sheet title="Funds & ETFs" meta={`${funds.length}`}>
                      <Holdings rows={funds} open={open} onToggle={toggle} />
                    </Sheet>
                  )}
                </div>
              )}

              {tab === 'rebalance' && <Rebalance snapshot={snapshot} onTrade={account === 'mine' ? setTicket : null} />}

              {tab === 'mix' && <Concentration concentration={snapshot.concentration} count={snapshot.totals.count} />}

              {tab === 'review' &&
                (snapshot.summary ? (
                  <Sheet title="Review" meta="AI write-up of the figures">
                    <div className="text-sm leading-relaxed">
                      <Markdown>{snapshot.summary}</Markdown>
                    </div>
                  </Sheet>
                ) : (
                  <Sheet>
                    <Empty title="No write-up yet" detail="Analyse now to have the figures explained." />
                  </Sheet>
                ))}
            </div>
          </div>
        )}
      </div>
      {ticket && <OrderTicket {...ticket} venue="mine" onClose={() => setTicket(null)} />}
    </Layout>
  );
};

export default MyPortfolio;
