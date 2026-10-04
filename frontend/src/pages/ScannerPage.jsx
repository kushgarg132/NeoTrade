import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScanLine, Loader2, ArrowRight } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import { Sheet, Statement, Row, Cell, Empty, Ruling, Field, Scrip, Tabs } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { formatCurrency, formatSignedPercent } from '../utils/formatters';
import { cn } from '../utils/cn';
import OrderTicket, { TicketButton } from '../components/trading/OrderTicket';

/**
 * The scan: the user's universe swept for two named setups -- a breakout and a
 * pullback in an uptrend -- on completed daily bars. Stops come from ATR,
 * targets are 2R. These are leads, not proposals — a proposal carries sizing
 * and lives on the decisions page.
 */

const SETUP_LABEL = { breakout: 'Breakout', pullback: 'Pullback' };

const Change = ({ value }) => (
  <span className={cn('figure-md text-sm', value >= 0 ? 'text-up' : 'text-down')}>
    {formatSignedPercent(value)}
  </span>
);

const ScannerPage = () => {
  const [scan, setScan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [showSkipped, setShowSkipped] = useState(false);
  const [ticket, setTicket] = useState(null);
  const navigate = useNavigate();

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get(endpoints.scanner);
      setScan(response.data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'The scanner is unreachable.');
    } finally {
      setLoading(false);
    }
  };

  const open = (symbol) => navigate('/research', { state: { symbol } });
  const findings = scan?.findings ?? [];
  const shown = filter === 'all' ? findings : findings.filter((f) => f.setup === filter);
  const count = (setup) => findings.filter((f) => f.setup === setup).length;

  const meta = scan
    ? [
        scan.as_of &&
          `As of ${new Date(scan.as_of).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} close`,
        `run ${new Date(scan.scan_time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`,
      ]
        .filter(Boolean)
        .join(' · ')
    : undefined;

  return (
    <Layout>
      <div className="space-y-4">
        <SectionTabs tabs={RESEARCH_TABS} label="Research" />
        <Sheet
          title="Scanner"
          meta={meta}
          actions={
            <Button variant="primary" size="sm" onClick={run} disabled={loading}>
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <ScanLine className="w-3.5 h-3.5" />
              )}
              {loading ? 'Scanning' : 'Run scan'}
            </Button>
          }
        >
          <p className="text-sm text-[var(--ink-soft)]">
            Sweeps your universe{scan ? ` (${scan.scanned} scrips)` : ''} for breakouts and
            pullbacks in an uptrend, on completed daily bars. Findings are leads to enquire on —
            sized proposals with a stop arrive on the decisions page instead.
          </p>
          {scan?.skipped?.length > 0 && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setShowSkipped((v) => !v)}
                aria-expanded={showSkipped}
                className="doc-meta normal-case underline decoration-dotted min-h-11 sm:min-h-0"
              >
                Skipped {scan.skipped.length}: no data or under 200 bars
              </button>
              {showSkipped && (
                <ul className="mt-1 doc-meta normal-case">
                  {scan.skipped.map((s) => (
                    <li key={s.symbol}>
                      {s.symbol} — {s.reason}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {error && (
            <p
              role="alert"
              className="mt-3 text-sm text-[var(--loss)] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2"
            >
              {error}
            </p>
          )}
        </Sheet>

        {loading ? (
          <Sheet title="Scanning">
            <Ruling rows={5} />
          </Sheet>
        ) : scan === null ? (
          <Sheet>
            <Empty
              title="No scan run yet"
              detail="Run a scan to see which scrips in your universe are breaking out or pulling back in an uptrend."
            />
          </Sheet>
        ) : findings.length === 0 ? (
          <Sheet>
            <Empty
              title="Nothing set up"
              detail="No scrip in your universe is breaking out or pulling back in an uptrend right now."
            />
          </Sheet>
        ) : (
          <Sheet title="Findings" meta={`${findings.length}`}>
            <Tabs
              tabs={[
                { id: 'all', label: 'All', count: findings.length },
                { id: 'breakout', label: 'Breakout', count: count('breakout') },
                { id: 'pullback', label: 'Pullback', count: count('pullback') },
              ]}
              active={filter}
              onSelect={setFilter}
              label="Filter findings by setup"
              className="static z-auto mb-2"
            />

            {/* Phone: stacked findings with their reasons. */}
            <ul className="sm:hidden">
              {shown.map((pick) => (
                <li key={pick.symbol} className="py-3 border-b border-[var(--rule)] last:border-b-0">
                  <button type="button" onClick={() => open(pick.symbol)} className="w-full text-left">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="inline-flex items-baseline gap-2">
                        <span className="figure-md text-sm">{pick.symbol}</span>
                        <Badge variant="secondary">{SETUP_LABEL[pick.setup]}</Badge>
                      </span>
                      <Change value={pick.change_pct} />
                    </div>
                    <div className="mt-2 grid grid-cols-4 gap-3">
                      <Field label="Last" value={formatCurrency(pick.close)} />
                      <Field label={`Stop ${pick.risk_pct}%`} value={formatCurrency(pick.stop)} tone="down" />
                      <Field label="Target 2R" value={formatCurrency(pick.target)} tone="up" />
                      <Field label="3M" value={formatSignedPercent(pick.return_3m)} />
                    </div>
                    <p className="mt-2 doc-meta normal-case">{pick.reasons.join(' · ')}</p>
                  </button>
                  <div className="mt-2">
                    <TicketButton label="Buy" onClick={() => setTicket({ symbol: pick.symbol, lastPrice: pick.close })} />
                  </div>
                </li>
              ))}
            </ul>

            <div className="hidden sm:block">
              <Statement
                columns={[
                  { key: 'scrip', label: 'Scrip' },
                  { key: 'last', label: 'Last', align: 'right' },
                  { key: 'change', label: 'Change', align: 'right' },
                  { key: 'stop', label: 'Stop', align: 'right' },
                  { key: 'target', label: 'Target (2R)', align: 'right' },
                  { key: 'r3m', label: '3M', align: 'right' },
                ]}
              >
                {shown.map((pick) => (
                  <Row
                    key={pick.symbol}
                    className="group cursor-pointer hover:bg-[var(--paper-sunk)]"
                    onClick={() => open(pick.symbol)}
                  >
                    <Cell>
                      <span className="inline-flex items-baseline gap-2">
                        <Scrip symbol={pick.symbol} />
                        <Badge variant="secondary">{SETUP_LABEL[pick.setup]}</Badge>
                      </span>
                      <span className="block doc-meta normal-case truncate max-w-[22rem]">
                        {pick.reasons.join(' · ')}
                      </span>
                    </Cell>
                    <Cell align="right" mono>
                      {formatCurrency(pick.close)}
                    </Cell>
                    <Cell align="right">
                      <Change value={pick.change_pct} />
                    </Cell>
                    <Cell align="right" mono className="text-down">
                      {formatCurrency(pick.stop)}
                      <span className="block doc-meta">{pick.risk_pct}%</span>
                    </Cell>
                    <Cell align="right" mono className="text-up">
                      {formatCurrency(pick.target)}
                    </Cell>
                    <Cell align="right">
                      <span className="inline-flex items-center gap-2">
                        <Change value={pick.return_3m} />
                        <TicketButton label="Buy" onClick={() => setTicket({ symbol: pick.symbol, lastPrice: pick.close })} />
                        <ArrowRight
                          className="w-4 h-4 text-[var(--ink-faint)] group-hover:text-[var(--stamp)] transition-colors"
                          aria-hidden="true"
                        />
                      </span>
                    </Cell>
                  </Row>
                ))}
              </Statement>
            </div>
          </Sheet>
        )}
      </div>
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} />}
    </Layout>
  );
};

export default ScannerPage;
