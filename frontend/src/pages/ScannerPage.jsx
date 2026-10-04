import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ScanLine, Loader2, ArrowRight } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import { Sheet, Statement, Row, Cell, Empty, Ruling, Field, Scrip } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { formatCurrency, formatSignedPercent } from '../utils/formatters';
import { cn } from '../utils/cn';

/**
 * The bullish scan: a one-off sweep of the universe, reported as findings.
 * These are leads, not proposals — a proposal carries sizing and a stop and
 * lives on the decisions page.
 */
const ScannerPage = () => {
  const [results, setResults] = useState(null);
  const [scanTime, setScanTime] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.get(endpoints.scanner);
      setResults(response.data.bullish_picks);
      setScanTime(response.data.scan_time);
    } catch (err) {
      setError(err?.response?.data?.detail || 'The scanner is unreachable.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout>
      <div className="space-y-4">
        <SectionTabs tabs={RESEARCH_TABS} label="Research" />
        <Sheet
          title="Scanner"
          meta={scanTime ? `Last run ${new Date(scanTime).toLocaleTimeString('en-IN')}` : undefined}
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
            Sweeps the NIFTY universe for bullish technical setups. Findings are leads to
            enquire on — sized proposals with a stop arrive on the decisions page instead.
          </p>
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
        ) : results === null ? (
          <Sheet>
            <Empty
              title="No scan run yet"
              detail="Run a scan to see what the technical filters are picking up right now."
            />
          </Sheet>
        ) : results.length === 0 ? (
          <Sheet>
            <Empty title="Nothing bullish" detail="No scrip in the universe met the filters." />
          </Sheet>
        ) : (
          <Sheet title="Findings" meta={`${results.length}`}>
            {/* Phone: stacked findings with their reasons. */}
            <ul className="sm:hidden">
              {results.map((pick) => (
                <li key={pick.symbol} className="py-3 border-b border-[var(--rule)] last:border-b-0">
                  <button
                    type="button"
                    onClick={() => navigate('/', { state: { symbol: pick.symbol } })}
                    className="w-full text-left"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="figure-md text-sm">{pick.symbol}</span>
                      <span
                        className={cn(
                          'figure-md text-sm',
                          pick.change_percent >= 0 ? 'text-up' : 'text-down'
                        )}
                      >
                        {formatSignedPercent(pick.change_percent)}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-3">
                      <Field label="Last" value={formatCurrency(pick.current_price)} />
                      <Field label="Target" value={formatCurrency(pick.target_price)} tone="up" />
                      <Field label="Stop" value={formatCurrency(pick.stop_loss)} tone="down" />
                    </div>
                    {pick.reasons?.length > 0 && (
                      <p className="mt-2 doc-meta normal-case">{pick.reasons.join(' · ')}</p>
                    )}
                  </button>
                </li>
              ))}
            </ul>

            <div className="hidden sm:block">
              <Statement
                columns={[
                  { key: 'scrip', label: 'Scrip' },
                  { key: 'last', label: 'Last', align: 'right' },
                  { key: 'change', label: 'Change', align: 'right' },
                  { key: 'target', label: 'Target', align: 'right' },
                  { key: 'stop', label: 'Stop', align: 'right' },
                  { key: 'conf', label: 'Confidence', align: 'right' },
                ]}
              >
                {results.map((pick) => (
                  <Row
                    key={pick.symbol}
                    className="group cursor-pointer hover:bg-[var(--paper-sunk)]"
                    onClick={() => navigate('/', { state: { symbol: pick.symbol } })}
                  >
                    <Cell>
                      <Scrip symbol={pick.symbol} />
                      <span className="block doc-meta normal-case truncate max-w-[18rem]">
                        {pick.reasons?.join(' · ')}
                      </span>
                    </Cell>
                    <Cell align="right" mono>
                      {formatCurrency(pick.current_price)}
                    </Cell>
                    <Cell align="right">
                      <span
                        className={cn(
                          'figure-md text-sm',
                          pick.change_percent >= 0 ? 'text-up' : 'text-down'
                        )}
                      >
                        {formatSignedPercent(pick.change_percent)}
                      </span>
                    </Cell>
                    <Cell align="right" mono className="text-up">
                      {formatCurrency(pick.target_price)}
                    </Cell>
                    <Cell align="right" mono className="text-down">
                      {formatCurrency(pick.stop_loss)}
                    </Cell>
                    <Cell align="right">
                      <span className="inline-flex items-center gap-2">
                        <Badge variant="secondary">{pick.confidence}%</Badge>
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
    </Layout>
  );
};

export default ScannerPage;
