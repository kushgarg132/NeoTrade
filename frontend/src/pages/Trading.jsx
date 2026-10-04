import React, { useEffect, useState } from 'react';
import { Play, Square, Loader2, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import { paperPositions } from '../utils/books';
import TradingControlBar from '../components/trading/TradingControlBar';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine, Scrip } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
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
  const [universeSymbols, setUniverseSymbols] = useState([]);
  const [accountSize, setAccountSize] = useState(1_000_000);
  const [maxExposure, setMaxExposure] = useState(1_000_000);
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [killSwitch, setKillSwitch] = useState(null);
  const [liveStrategies, setLiveStrategies] = useState([]);
  const [prefs, setPrefs] = useState(null);
  const [longterm, setLongterm] = useState({ pending: 0, open: 0 });
  const [scan, setScan] = useState(null);
  const [stopping, setStopping] = useState(null);

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

  const loadLongterm = () =>
    Promise.all([
      api.get(endpoints.suggestions.list({ status: 'PENDING', mode: 'LONGTERM' })),
      api.get(endpoints.trading.trades('OPEN', 'paper', 'LONGTERM')),
    ])
      .then(([pendingRes, openRes]) => setLongterm({ pending: pendingRes.data.length, open: openRes.data.length }))
      .catch(() => {});

  const loadLedger = () =>
    Promise.all([api.get(endpoints.trading.positions('paper')), api.get(endpoints.trading.fills('paper'))])
      .then(([positionsRes, fillsRes]) => {
        setPositions(positionsRes.data);
        setFills(fillsRes.data);
      })
      .catch(() => {});

  useEffect(() => {
    Promise.all([loadRuns(), loadLedger(), loadKillSwitch(), loadLongterm()]).finally(() => setLoading(false));
    // Which strategies trade real money when a run starts here.
    api
      .get(endpoints.settings.preferences)
      .then((res) => {
        setPrefs(res.data);
        setLiveStrategies(res.data.live_strategies || []);
      })
      .catch(() => setLiveStrategies([]));
  }, []);

  useTopic('runs', (message) => {
    // Progress ticks arrive every few seconds while a run polls; patch in place
    // rather than refetching every run on each one.
    if (message.event !== 'progress') {
      loadRuns();
      return;
    }
    const { run_id: runId, progress } = message.data;
    setRuns((current) => current.map((run) => (run.run_id === runId ? { ...run, progress } : run)));
  });
  useTopic('positions', (message) => setPositions(paperPositions(message.data)));
  useTopic('trades', () => {
    loadLedger();
    loadKillSwitch();
    loadLongterm();
  });
  useTopic('suggestions', loadLongterm);

  // Intraday and any leftover long-term run can be live at once; each gets
  // its own line and its own Stop.
  const running = runs.filter((run) => run.status === 'RUNNING');
  const intradayActive = running.some((run) => run.mode === 'INTRADAY');
  // Newest first from the server: a crash is said out loud, not shown as "Idle".
  const crashed = running.length === 0 && runs[0]?.status === 'ERROR' ? runs[0] : null;

  const start = async () => {
    setBusy(true);
    setStartError(null);
    try {
      await api.post(endpoints.trading.start, {
        mode: 'INTRADAY',
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

  const stop = async (run) => {
    setStopping(run.run_id);
    setStartError(null);
    try {
      await api.post(endpoints.trading.stop, { run_id: run.run_id });
    } catch (err) {
      if (err.response?.status !== 404) {
        setStartError(err.response?.data?.detail || 'Could not stop the run.');
      }
    } finally {
      await loadRuns();
      setStopping(null);
    }
  };

  const scanNow = async () => {
    setScan('starting');
    try {
      const res = await api.post(endpoints.suggestions.scan, {});
      setScan(`Scanning ${res.data.symbols} scrip. New proposals land under Decisions in a few minutes.`);
    } catch (err) {
      setScan(err?.response?.data?.detail || 'Could not start the scan.');
    }
  };

  const openPositions = Object.values(positions);
  const realised = openPositions.reduce((total, p) => total + (p.realized_pnl || 0), 0);
  const recentFills = [...fills]
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .slice(0, 25);

  return (
    <Layout>
      <PaperShell>
        {liveStrategies.length > 0 && (
          <div className="sheet px-4 py-3 border-[var(--loss)] bg-[var(--loss-wash)]" role="status">
            <p className="field-label text-[var(--loss)]">Live mode armed</p>
            <p className="mt-1 text-sm text-[var(--ink)]">
              {liveStrategies.join(', ')} {liveStrategies.length === 1 ? 'trades' : 'trade'} real
              money when a run starts. Those orders go to your broker and print on the{' '}
              <Link to="/" className="underline decoration-[var(--loss)] underline-offset-2">
                statement
              </Link>
              , not in this paper book.
            </p>
          </div>
        )}
        <Sheet
          title="Intraday engine"
          meta={running.length ? `${running.length} running` : 'Idle'}
          actions={
            !intradayActive && (
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
          {crashed && (
            <p className="mb-3 text-sm text-[var(--loss)]" role="alert">
              Last run stopped {formatTimeAgo(crashed.stopped_at)}: {crashed.error}
            </p>
          )}
          {running.map((run) => (
            <div key={run.run_id} className="flex flex-wrap items-center gap-3 py-2 border-b border-[var(--rule)] last:border-b-0">
              <Badge variant="success">Running</Badge>
              <Badge variant="secondary">{run.mode === 'INTRADAY' ? 'Intraday' : 'Long term'}</Badge>
              {run.params?.origin === 'auto' && <Badge variant="outline">Auto-run</Badge>}
              <span className="doc-meta normal-case">
                since {formatTimeAgo(run.started_at)} · {run.universe.length} scrip · run {run.run_id.slice(0, 8)}
                {run.params?.feed && ` · ${run.params.feed}`}
              </span>
              <Button variant="danger" size="sm" className="ml-auto" onClick={() => stop(run)} disabled={stopping === run.run_id}>
                {stopping === run.run_id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" />}
                Stop
              </Button>
              <span className="doc-meta normal-case w-full">
                {run.progress
                  ? `${run.progress.bars} bars scanned · ${run.progress.signals} signals · ${run.progress.orders} orders · last ${run.progress.last_symbol ?? 'bar'} at ${formatClock(run.progress.updated_at)}`
                  : 'Waiting for the first bar…'}
              </span>
            </div>
          ))}
          {!intradayActive && (
            <div className={cn(running.length > 0 && 'mt-4')}>
              <TradingControlBar
                universeSymbols={universeSymbols}
                onUniverseChange={setUniverseSymbols}
                accountSize={accountSize}
                onAccountSizeChange={setAccountSize}
                maxExposure={maxExposure}
                onMaxExposureChange={setMaxExposure}
                startError={startError}
              />
            </div>
          )}
          {startError && intradayActive && <p className="mt-3 text-sm text-[var(--loss)]">{startError}</p>}
        </Sheet>

        <Sheet
          title="Long-term engine"
          meta={prefs ? (prefs.auto_paper_longterm ? 'On' : 'Off') : undefined}
          actions={
            <Button variant="secondary" size="sm" onClick={scanNow} disabled={scan === 'starting'}>
              {scan === 'starting' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
              Scan now
            </Button>
          }
        >
          <p className="text-sm text-[var(--ink)]">
            Scans a year of daily prices after each close (16:00 IST) and files what it finds under{' '}
            <Link to="/ai/practice/decisions" className="underline underline-offset-2">Decisions</Link>.
            {prefs?.auto_paper_longterm
              ? ' At 09:20 on the first trading day of each month the factor portfolio rebalances on paper; in session, approved positions are sold at their stop or target, checked every 15 minutes.'
              : ' Turn on the daily long-term engine in Settings to close approved positions at their stop or target.'}
          </p>
          <p className="mt-2 doc-meta normal-case">
            {longterm.pending} waiting for your decision · {longterm.open} open long-term position{longterm.open === 1 ? '' : 's'}
          </p>
          {scan && scan !== 'starting' && <p className="mt-2 text-sm text-[var(--ink-soft)]">{scan}</p>}
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
                      <Scrip symbol={position.symbol} />
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
                    <Scrip symbol={fill.symbol} />
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
      </PaperShell>
    </Layout>
  );
};

export default Trading;
