import React, { useEffect, useState } from 'react';
import { Play, Square, Loader2 } from 'lucide-react';
import Layout from '../components/Layout';
import TradingControlBar from '../components/trading/TradingControlBar';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { useTopic } from '../hooks/useStream';
import {
  formatCurrency,
  formatQuantity,
  formatClock,
  formatTimeAgo,
} from '../utils/formatters';

/**
 * The engine's own page: what is running, and the raw executions behind the
 * statement.
 *
 * Runs are read from the server rather than remembered in localStorage — the
 * backend now records them, so a reload, a second device, or a restart all
 * agree on what is actually live.
 */
const Trading = () => {
  const [runs, setRuns] = useState([]);
  const [positions, setPositions] = useState({});
  const [fills, setFills] = useState([]);
  const [mode, setMode] = useState('LONGTERM');
  const [universeSymbols, setUniverseSymbols] = useState([]);
  const [accountSize, setAccountSize] = useState(1_000_000);
  const [maxExposure, setMaxExposure] = useState(1_000_000);
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [killSwitch, setKillSwitch] = useState(null);

  const loadKillSwitch = () =>
    api
      .get(endpoints.trading.killSwitch)
      .then((res) => setKillSwitch(res.data))
      .catch(() => setKillSwitch(null));

  const loadRuns = () =>
    api
      .get(endpoints.trading.runs)
      .then((res) => setRuns(res.data))
      .catch(() => setRuns([]));

  const loadLedger = () =>
    Promise.all([api.get(endpoints.trading.positions), api.get(endpoints.trading.fills)])
      .then(([positionsRes, fillsRes]) => {
        setPositions(positionsRes.data);
        setFills(fillsRes.data);
      })
      .catch(() => {});

  useEffect(() => {
    Promise.all([loadRuns(), loadLedger(), loadKillSwitch()]).finally(() => setLoading(false));
  }, []);

  useTopic('runs', loadRuns);
  useTopic('positions', (message) => setPositions(message.data));
  useTopic('trades', () => {
    loadLedger();
    loadKillSwitch();
  });

  const active = runs.find((run) => run.status === 'RUNNING');

  const start = async () => {
    setBusy(true);
    setStartError(null);
    try {
      await api.post(endpoints.trading.start, {
        mode,
        universe: universeSymbols.length > 0 ? universeSymbols : undefined,
        account_size: accountSize,
        max_exposure: maxExposure,
      });
      await loadRuns();
    } catch (err) {
      setStartError(err.response?.data?.detail || 'Could not start the run.');
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!active) return;
    setBusy(true);
    setStartError(null);
    try {
      await api.post(endpoints.trading.stop, { run_id: active.run_id });
    } catch (err) {
      if (err.response?.status !== 404) {
        setStartError(err.response?.data?.detail || 'Could not stop the run.');
      }
    } finally {
      await loadRuns();
      setBusy(false);
    }
  };

  const openPositions = Object.values(positions);
  const realised = openPositions.reduce((total, p) => total + (p.realized_pnl || 0), 0);
  const recentFills = [...fills]
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .slice(0, 25);

  return (
    <Layout>
      <div className="space-y-4">
        <Sheet
          title="Engine"
          meta={active ? `Running since ${formatTimeAgo(active.started_at)}` : 'Idle'}
          actions={
            active ? (
              <Button variant="danger" size="sm" onClick={stop} disabled={busy}>
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" />}
                Stop
              </Button>
            ) : (
              <Button variant="primary" size="sm" onClick={start} disabled={busy}>
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                Start
              </Button>
            )
          }
        >
          {killSwitch?.tripped && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Badge variant="destructive">Kill-switch tripped</Badge>
              <span className="doc-meta normal-case">
                {killSwitch.reason} · no new intraday orders for the rest of today.
              </span>
            </div>
          )}
          {active ? (
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="success">Running</Badge>
              <Badge variant="secondary">{active.mode === 'INTRADAY' ? 'Intraday' : 'Long term'}</Badge>
              <span className="doc-meta normal-case">
                {active.universe.length} scrip · run {active.run_id.slice(0, 8)}
              </span>
              {active.mode === 'LONGTERM' && (
                <p className="w-full text-sm text-[var(--ink-soft)]">
                  Long-term signals from this run file as proposals for your decision rather
                  than executing.
                </p>
              )}
            </div>
          ) : (
            <TradingControlBar
              mode={mode}
              onModeChange={setMode}
              universeSymbols={universeSymbols}
              onUniverseChange={setUniverseSymbols}
              accountSize={accountSize}
              onAccountSizeChange={setAccountSize}
              maxExposure={maxExposure}
              onMaxExposureChange={setMaxExposure}
              isActive={false}
              onStart={start}
              onStop={stop}
              busy={busy}
              startError={startError}
            />
          )}

          {startError && active && (
            <p className="mt-3 text-sm text-[var(--loss)]">{startError}</p>
          )}
        </Sheet>

        <Sheet title="Positions" meta={`${openPositions.length} open`}>
          {loading ? (
            <Ruling rows={3} />
          ) : openPositions.length === 0 ? (
            <Empty title="Flat" detail="No open position on the book." />
          ) : (
            <>
              <Statement
                columns={[
                  { key: 'scrip', label: 'Scrip' },
                  { key: 'qty', label: 'Qty', align: 'right' },
                  { key: 'avg', label: 'Avg', align: 'right' },
                  { key: 'realised', label: 'Realised', align: 'right' },
                ]}
              >
                {openPositions.map((position) => (
                  <Row key={position.symbol}>
                    <Cell>
                      <span className="figure-md">{position.symbol}</span>
                    </Cell>
                    <Cell align="right" mono>
                      {formatQuantity(position.quantity)}
                    </Cell>
                    <Cell align="right" mono>
                      {formatCurrency(position.avg_price)}
                    </Cell>
                    <Cell align="right">
                      <Money value={position.realized_pnl} />
                    </Cell>
                  </Row>
                ))}
              </Statement>
              <NetLine label="Realised on open scrip">
                <Money value={realised} />
              </NetLine>
            </>
          )}
        </Sheet>

        <Sheet title="Executions" meta={`${fills.length} fills`}>
          {loading ? (
            <Ruling rows={3} />
          ) : recentFills.length === 0 ? (
            <Empty title="No executions yet" detail="Fills appear here as orders are filled." />
          ) : (
            <Statement
              columns={[
                { key: 'scrip', label: 'Scrip' },
                { key: 'time', label: 'Time' },
                { key: 'side', label: 'Side' },
                { key: 'qty', label: 'Qty', align: 'right' },
                { key: 'price', label: 'Price', align: 'right' },
                { key: 'costs', label: 'Charges', align: 'right' },
              ]}
            >
              {recentFills.map((fill) => (
                <Row key={`${fill.order_id}-${fill.timestamp}`}>
                  <Cell>
                    <span className="figure-md">{fill.symbol}</span>
                  </Cell>
                  <Cell className="doc-meta normal-case">{formatClock(fill.timestamp)}</Cell>
                  <Cell>
                    <Badge variant={fill.side === 'BUY' ? 'success' : 'destructive'}>
                      {fill.side}
                    </Badge>
                  </Cell>
                  <Cell align="right" mono>
                    {formatQuantity(fill.quantity)}
                  </Cell>
                  <Cell align="right" mono>
                    {formatCurrency(fill.price)}
                  </Cell>
                  <Cell align="right" mono className="text-[var(--ink-faint)]">
                    {formatCurrency(fill.costs)}
                  </Cell>
                </Row>
              ))}
            </Statement>
          )}
        </Sheet>
      </div>
    </Layout>
  );
};

export default Trading;
