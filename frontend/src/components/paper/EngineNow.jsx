import React, { useEffect, useState } from 'react';
import { Play, Square, Loader2, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import TradingControlBar from '../trading/TradingControlBar';
import { Sheet } from '../doc/Doc';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import api, { endpoints } from '../../utils/api';
import { cn } from '../../utils/cn';
import { useReconnect, useTopic } from '../../hooks/useStream';
import { formatClock, formatTimeAgo } from '../../utils/formatters';

/**
 * What the strategy engine is doing now: the live-mode warning, the intraday
 * run (start, stop, progress) and the long-term engine (daily scan, pending
 * and open counts). Moved from the old Engine page onto the Practice overview.
 * `prefs` is the user's preferences, fetched once by the overview (null until
 * loaded or when the fetch failed).
 */
const EngineNow = ({ prefs }) => {
  const [runs, setRuns] = useState([]);
  const [universeSymbols, setUniverseSymbols] = useState([]);
  const [runSettings, setRunSettings] = useState(false);
  const [accountSize, setAccountSize] = useState(1_000_000);
  const [maxExposure, setMaxExposure] = useState(1_000_000);
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState(null);
  const [killSwitch, setKillSwitch] = useState(null);
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

  useEffect(() => {
    loadRuns();
    loadKillSwitch();
    loadLongterm();
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
  useTopic('trades', () => {
    loadKillSwitch();
    loadLongterm();
  });
  useTopic('suggestions', loadLongterm);
  useReconnect(() => {
    loadRuns();
    loadKillSwitch();
    loadLongterm();
  });

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

  // Which strategies trade real money when a run starts here.
  const liveStrategies = prefs?.live_strategies || [];

  return (
    <>
        {liveStrategies.length > 0 && (
          <div className="sheet px-4 py-3 border-[var(--loss)] bg-[var(--loss-wash)]" role="status">
            <p className="field-label text-[var(--loss)]">Live mode armed</p>
            <p className="mt-1 text-sm text-[var(--ink)]">
              {liveStrategies.join(', ')} {liveStrategies.length === 1 ? 'trades' : 'trade'} real
              money when a run starts. Those orders go to your broker and print on the{' '}
              <Link to="/mine/trades" className="underline decoration-[var(--loss)] underline-offset-2">
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
            <button
              type="button"
              onClick={() => setRunSettings((value) => !value)}
              aria-expanded={runSettings}
              className={cn('field-label text-[var(--stamp)] hover:underline min-h-11 sm:min-h-0', running.length > 0 && 'mt-3')}
            >
              {runSettings ? 'Hide run settings' : `Run settings · ${universeSymbols.length || 'default'} scrip, ₹${Number(accountSize || 0).toLocaleString('en-IN')}`}
            </button>
          )}
          {!intradayActive && (runSettings || startError) && (
            <div className="mt-2">
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
              Long-term scan
            </Button>
          }
        >
          <p className="text-sm">
            Next scan 16:00 IST · {longterm.open} open long-term position{longterm.open === 1 ? '' : 's'}
            {prefs && !prefs.auto_paper_longterm && ' · stops and targets are not watched while it is off'}
          </p>
          {scan && scan !== 'starting' && <p className="mt-2 text-sm text-[var(--ink-soft)]">{scan}</p>}
        </Sheet>
    </>
  );
};

export default EngineNow;
