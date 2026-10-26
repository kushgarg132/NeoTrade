import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, RefreshCw, Upload, History } from 'lucide-react';
import Card from '../ui/Card';
import Tabs, { useTabParam } from '../ui/Tabs';
import Button from '../ui/Button';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import Skeleton from '../ui/Skeleton';
import Stat from '../ui/Stat';
import { inr, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import GuardrailsSheet from '../journal/GuardrailsSheet';
import GuardrailAlerts from '../journal/GuardrailAlerts';
import BrokerPnl from '../dashboard/BrokerPnl';
import LivePnl from '../journal/LivePnl';
import TradeLedger from '../dashboard/TradeLedger';
import MonthGrid from '../journal/MonthGrid';
import AiSummary from '../ai/AiSummary';
import { useLoad } from '../ideas/useLoad';
import { useReconnect, useTopic } from '../../hooks/useStream';
import { useAccount } from '../../hooks/useAccount';
import { monthKey, shiftMonth, monthLabel, todayIst } from '../../utils/months';
import api, { endpoints } from '../../utils/api';
import { formatQuantity, formatPercent, formatSigned, formatDateTime } from '../../utils/formatters';

/**
 * The journal for the user's own account: every fill from their broker, grouped into round trips.
 * It reports what the user did, it never says what to do next. Sub-tab in `?jtab=` (trades | habits | guardrails).
 */

const SUBTABS = [{ id: 'trades', label: 'Trades' }, { id: 'habits', label: 'Habits' }, { id: 'guardrails', label: 'Guardrails' }];
const SUBTAB_IDS = SUBTABS.map((t) => t.id);
const small = 'inline-flex items-center gap-1.5 min-h-11 px-3 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] text-[14px] font-medium text-[var(--text)] disabled:opacity-50';

/** The strongest scored news in the 24h before a trip's entry and exit (backend journal/news.py). */
const tripNews = (t) => [['Entry', t.news], ['Exit', t.exit_news]].filter(([, n]) => n);
const newsWord = (n) => (n.direction > 0 ? 'good news' : n.direction < 0 ? 'bad news' : 'news');
const hoursBefore = (m) => (m < 60 ? `${m} min` : `${Math.round(m / 60)} h`);

/** Small chips inside the trip row (a button, so no links here); the headlines show when it is tapped. */
const NewsChips = ({ trip }) => {
  const items = tripNews(trip);
  if (items.length === 0) return null;
  return (
    <span className="flex flex-wrap gap-1.5 mt-1">
      {items.map(([label, n]) => (
        <span key={label} className={`rounded-full bg-[var(--surface-2)] px-2 text-[12px] leading-5 ${toneText(tone(n.direction))}`}>
          {label}: {newsWord(n)}
        </span>
      ))}
    </span>
  );
};

const TripHeadlines = ({ trip }) => {
  const items = tripNews(trip);
  if (items.length === 0) return null;
  return (
    <ul className="mb-2 space-y-1 text-[13px]">
      {items.map(([label, n]) => (
        <li key={label} className="text-[var(--text-muted)]">
          <span className={toneText(tone(n.direction))}>{label}, {hoursBefore(n.minutes_before)} before: </span>
          {n.url ? <a href={n.url} target="_blank" rel="noreferrer" className="text-[var(--accent)] hover:underline">{n.headline || 'headline'}</a> : (n.headline || 'headline not stored')}
        </li>
      ))}
    </ul>
  );
};

const Finding = ({ finding }) => (
  <li className="py-3 border-b border-[var(--border)] last:border-b-0">
    <div className="flex items-baseline justify-between gap-3">
      <p className="text-[15px] text-[var(--text)]">{finding.title}</p>
      <span className={`private figure-md tabular-nums ${toneText(tone(finding.pnl))}`}>{inr(finding.pnl, { sign: true })}</span>
    </div>
    <p className="text-[13px] text-[var(--text-muted)] mt-1">
      {finding.trips} trades · win rate {formatPercent(finding.win_rate * 100)} against{' '}
      {formatPercent(finding.baseline_win_rate * 100)} on the rest · {formatSigned(finding.avg_pnl)} a trade
      against {formatSigned(finding.baseline_avg_pnl)}
    </p>
    {finding.note && <p className="text-[13px] text-[var(--text-muted)] mt-1">{finding.note}</p>}
  </li>
);

const NoteEditor = ({ trip, onSaved }) => {
  const [note, setNote] = useState(trip.note || '');
  const [tags, setTags] = useState((trip.tags || []).join(', '));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);

  const save = () => {
    setBusy(true);
    setFailed(null);
    api
      .put(endpoints.journal.note(trip.id), { note, tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean) })
      .then((res) => onSaved(trip.id, res.data))
      .catch((err) => setFailed(err?.response?.data?.detail || 'The note was not saved.'))
      .finally(() => setBusy(false));
  };
  const field = 'mt-1 w-full rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 text-[15px] text-[var(--text)]';

  return (
    <div className="space-y-3 py-3">
      <p className="text-[13px] text-[var(--text-muted)]">
        Opened {formatDateTime(trip.opened_at)}
        {trip.closed_at && ` · closed ${formatDateTime(trip.closed_at)}`} · {trip.broker}
      </p>
      <label className="block text-[13px] text-[var(--text-muted)]">
        Note
        <textarea
          value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={5000}
          placeholder="Why you took it, what you saw, how it went" className={`${field} py-2`}
        />
      </label>
      <label className="block text-[13px] text-[var(--text-muted)]">
        Tags, comma separated
        <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="breakout, fomo, planned" autoComplete="off" className={`${field} min-h-11`} />
      </label>
      <Button variant="secondary" onClick={save} disabled={busy}>{busy ? 'Saving' : 'Save note'}</Button>
      {failed && <p role="alert" className="text-[14px] text-[var(--loss)]">{failed}</p>}
    </div>
  );
};

const pctSigned = (x) => `${x >= 0 ? '+' : '−'}${Math.abs(x * 100).toFixed(1)}%`;

/** What charges took, how often they trade, and the Nifty over the same days. Charges are estimated. */
const MirrorCard = ({ mirror }) => {
  const c = mirror?.costs;
  if (!c || !c.fills) return null;
  const b = mirror.benchmark;
  return (
    <Card title="Charges and benchmark">
      <div className="grid grid-cols-2 gap-4">
        <Stat label="P&L before charges" value={inr(c.gross_pnl, { sign: true })} />
        <Stat label={`After ~${inr(c.charges)} charges`} value={inr(c.net_pnl, { sign: true })} />
        <Stat label="Trades per year" value={formatQuantity(c.trades_per_year)} />
        {b && <Stat label="You vs Nifty" value={`${pctSigned(b.your_return)} vs ${pctSigned(b.nifty_return)}`} />}
      </div>
      <p className="text-[13px] text-[var(--text-muted)] mt-3">
        {c.heavy_trader
          ? `SEBI found 80% of intraday traders with more than 500 trades a year lost money. You're on pace for ${formatQuantity(c.trades_per_year)}.`
          : 'Fewer trades means fewer charges: SEBI found 80% of intraday traders with more than 500 trades a year lost money.'}
        {b && ` Return on your account size since ${b.start}, against simply holding the Nifty.`}
      </p>
    </Card>
  );
};

const JournalTab = ({ onImport }) => {
  const [sub, setSub] = useTabParam(SUBTAB_IDS, 'trades', 'jtab');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [month, setMonth] = useState(null);
  const [selectedDay, setSelectedDay] = useState(null);
  const [openTrip, setOpenTrip] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const fileInput = useRef(null);
  const { account, roles, hasRole } = useAccount('mine');
  const trades = sub === 'trades';
  const habits = sub === 'habits';
  const guardrails = sub === 'guardrails';
  // Read only when the Habits tab is open: the weekly paragraph a job wrote.
  const words = useLoad(useCallback(() => (habits ? api.get(endpoints.summaries.habits).then((r) => r.data) : Promise.resolve(null)), [habits]));

  const load = (stale = () => false) =>
    api
      .get(endpoints.journal.get, { params: { account } })
      .then((res) => {
        if (stale()) return;
        setData(res.data);
        setError(null);
        setMonth((current) => {
          if (current) return current;
          const last = res.data.calendar[res.data.calendar.length - 1];
          return monthKey(last ? last.day : todayIst());
        });
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the journal.'));
  useEffect(() => {
    if (!account) return undefined;
    let gone = false;
    load(() => gone);
    return () => { gone = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  // Real orders a live strategy placed; only shown when one exists.
  const [liveTrades, setLiveTrades] = useState([]);
  const loadLiveTrades = () =>
    !trades
      ? Promise.resolve()
      : api.get(endpoints.trading.trades(null, 'live')).then((res) => setLiveTrades(res.data)).catch(() => setLiveTrades([]));
  useEffect(() => { loadLiveTrades(); }, [trades]); // eslint-disable-line react-hooks/exhaustive-deps
  useTopic('trades', loadLiveTrades);
  useReconnect(loadLiveTrades);
  // Real-money P&L, your account and the AI account as separate figures.
  const [livePnl, setLivePnl] = useState(null);
  const loadLivePnl = () => api.get(endpoints.analytics.pnl('live')).then((res) => setLivePnl(res.data)).catch(() => setLivePnl(null));
  useEffect(() => { loadLivePnl(); }, []);
  useReconnect(loadLivePnl);
  useTopic('pnl', (m) => m.data?.live && setLivePnl(m.data.live));

  const run = (request, describe) => {
    setBusy(true);
    setMessage(null);
    request()
      .then((res) => { setMessage(describe(res.data)); return load(); })
      .catch((err) => setMessage(err?.response?.data?.detail || 'That did not work.'))
      .finally(() => setBusy(false));
  };
  const sync = () =>
    run(
      () => api.post(endpoints.journal.sync),
      (r) =>
        r.brokers.length === 0 && r.failed.length === 0
          ? 'No broker is connected. Connect one in Settings, or import a Console tradebook.'
          : `${r.imported} new fill${r.imported === 1 ? '' : 's'} from ${r.brokers.join(', ') || 'no broker'}` +
            (r.failed.length ? `. ${r.failed.join(', ')} did not respond.` : '.')
    );
  const importUpstox = () =>
    run(
      () => api.post(endpoints.journal.importUpstox, { days: 730 }),
      (r) =>
        `${r.imported} fill${r.imported === 1 ? '' : 's'} imported from Upstox's last two years` +
        (r.skipped_synced_days ? `; ${r.skipped_synced_days} day(s) already synced were left as they were` : '') +
        '. History has dates but no times, so each day\'s fills are shown at 9:15 AM.'
    );
  const importCsv = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    file.text().then((csv) =>
      run(
        () => api.post(endpoints.journal.importConsole, { csv }),
        (r) =>
          `${r.imported} fill${r.imported === 1 ? '' : 's'} imported` +
          (r.duplicates ? `, ${r.duplicates} already in the journal` : '') +
          (r.skipped ? `, ${r.skipped} unreadable row${r.skipped === 1 ? '' : 's'} skipped` : '') + '.'
      )
    );
  };
  const onNoteSaved = (id, saved) =>
    setData((cur) => ({ ...cur, round_trips: cur.round_trips.map((t) => (t.id === id ? { ...t, ...saved } : t)) }));

  const byDay = useMemo(() => Object.fromEntries((data?.calendar || []).map((r) => [r.day, r])), [data]);
  const monthTotal = useMemo(
    () =>
      (data?.calendar || [])
        .filter((r) => month && monthKey(r.day) === month)
        .reduce((t, r) => ({ pnl: t.pnl + r.pnl, trips: t.trips + r.trips }), { pnl: 0, trips: 0 }),
    [data, month]
  );
  const trips = useMemo(() => {
    const all = data?.round_trips || [];
    return selectedDay ? all.filter((t) => t.day === selectedDay) : all.slice(0, 50);
  }, [data, selectedDay]);

  const summary = data?.summary;
  const empty = !data || data.round_trips.length === 0;
  const actions = (
    <div className="flex flex-wrap justify-end gap-2">
      <button type="button" className={small} onClick={sync} disabled={busy} aria-label="Sync today's trades"><RefreshCw className="w-4 h-4" />Sync</button>
      <button type="button" className={small} onClick={() => fileInput.current?.click()} disabled={busy} aria-label="Import a Zerodha Console CSV"><Upload className="w-4 h-4" />CSV</button>
      {data?.brokers_connected?.includes('upstox') && (
        <button type="button" className={small} onClick={importUpstox} disabled={busy} aria-label="Import Upstox trade history"><History className="w-4 h-4" />Upstox</button>
      )}
      <input ref={fileInput} type="file" accept=".csv,text/csv" className="hidden" onChange={importCsv} />
    </div>
  );
  const stepMonth = (by) => { setMonth(shiftMonth(month, by)); setSelectedDay(null); };
  const stepBtn = 'min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]';

  return (
    <div className="space-y-4">
      {roles && !hasRole && (
        <Link to="/settings?tab=accounts" className="block rounded-[16px] border border-dashed border-[var(--border)] px-4 py-3 text-[14px] text-[var(--text-muted)]">
          Showing every account. Set which broker is yours in Settings, Accounts.
        </Link>
      )}
      <GuardrailAlerts />
      <Tabs tabs={SUBTABS} value={sub} onChange={setSub} label="Journal sections" />

      {guardrails && <GuardrailsSheet />}

      {!guardrails && !data && !error && <Card><Skeleton rows={6} /></Card>}
      {!guardrails && error && <Card title="Journal"><ErrorLine message={error} onRetry={() => load()} /></Card>}

      {trades && (
        <>
          <div className="private space-y-4">
            <BrokerPnl journal={data} loading={!data && !error} error={error} />
            <LivePnl live={livePnl} />
            {liveTrades.length > 0 && <TradeLedger title="Orders placed from NeoTrade" trades={liveTrades} loading={false} error={null} />}
          </div>
          {data && (
            <Card title="Journal" action={actions}>
              {message && <p className="text-[13px] text-[var(--text-muted)] mb-3">{message}</p>}
              {empty ? (
                <Empty
                  title="No trades in the journal yet"
                  body="Sync pulls today's fills from every connected broker, and runs on its own after the close. For older history, import your Zerodha Console tradebook CSV."
                  action={<Button onClick={onImport}>Import files</Button>}
                />
              ) : (
                <div className="private">
                  <div className="flex items-center justify-between mb-2">
                    <button type="button" className={stepBtn} onClick={() => stepMonth(-1)} aria-label="Previous month"><ChevronLeft size={18} /></button>
                    <span className="text-[15px] font-semibold text-[var(--text)]">{monthLabel(month)}</span>
                    <button type="button" className={stepBtn} onClick={() => stepMonth(1)} aria-label="Next month"><ChevronRight size={18} /></button>
                  </div>
                  <MonthGrid month={month} byDay={byDay} selected={selectedDay} onSelect={setSelectedDay} />
                  <div className="grid grid-cols-3 gap-3 mt-4">
                    <Stat label={`${monthLabel(month)}`} value={inr(monthTotal.pnl, { sign: true })} delta={`${monthTotal.trips} closed`} tone={tone(monthTotal.pnl)} />
                    <Stat label="All time" value={inr(summary.pnl, { sign: true })} tone={tone(summary.pnl)} />
                    <Stat label="Strike rate" value={summary.trips ? formatPercent((summary.wins / summary.trips) * 100) : '—'} />
                  </div>
                  {summary.by_kind && Object.keys(summary.by_kind).length > 1 && (
                    <div className="grid grid-cols-3 gap-3 mt-4 pt-3 border-t border-[var(--border)]">
                      {['stocks', 'options', 'futures'].filter((k) => summary.by_kind[k]).map((kind) => (
                        <Stat key={kind} label={`${kind} · ${summary.by_kind[kind].trips}`} value={inr(summary.by_kind[kind].pnl, { sign: true })} tone={tone(summary.by_kind[kind].pnl)} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </Card>
          )}
          {data && !empty && (
            <Card
              title={selectedDay ? `Closed ${selectedDay}` : 'Recent round trips'}
              action={selectedDay && <button type="button" className={small} onClick={() => setSelectedDay(null)}>All</button>}
            >
              <p className="text-[13px] text-[var(--text-muted)] -mt-2 mb-1">Gross of charges. Tap a trade to add a note.</p>
              <div className="private">
                {trips.map((t) => (
                  <div key={t.id} className="border-b border-[var(--border)] last:border-b-0">
                    <button
                      type="button" aria-expanded={openTrip === t.id}
                      onClick={() => setOpenTrip(openTrip === t.id ? null : t.id)}
                      className="flex w-full items-center gap-3 min-h-14 py-2 text-left"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block text-[15px] font-medium text-[var(--text)] truncate">
                          {t.symbol} <span className="text-[13px] font-normal text-[var(--text-muted)]">{t.direction === 'SHORT' ? 'Short' : 'Long'}{t.kind && t.kind !== 'STOCK' ? ` · ${t.kind === 'FUTURE' ? 'FUT' : t.kind}` : ''}</span>
                        </span>
                        <span className="block text-[13px] text-[var(--text-muted)] truncate tabular-nums">
                          {formatQuantity(t.quantity)} · {inr(t.entry_price)} to {t.exit_price === null ? 'open' : inr(t.exit_price)}
                          {t.tags?.length > 0 && ` · ${t.tags.join(' · ')}`}
                        </span>
                        <NewsChips trip={t} />
                      </span>
                      <span className={`figure-md shrink-0 text-[15px] tabular-nums ${toneText(tone(t.pnl))}`}>{inr(t.pnl, { sign: true })}</span>
                    </button>
                    {openTrip === t.id && (
                      <>
                        <TripHeadlines trip={t} />
                        <NoteEditor trip={t} onSaved={onNoteSaved} />
                      </>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      {habits && data && (
        empty ? (
          <Empty title="No trades yet" body="Habits show once the journal has closed trades." action={<Button onClick={onImport}>Import files</Button>} />
        ) : (
          <>
            <AiSummary title="What your trades say" state={words} emptyBody="Written once a week, on the week's last trading day." />
            <MirrorCard mirror={data.mirror} />
            <Card title="Your patterns">
              {data.insights.length === 0 ? (
                <Empty title="Not enough trades to see a pattern" body="A pattern shows once it covers at least 5 closed trades. Tags you add are counted too." />
              ) : (
                <ul>{data.insights.map((f) => <Finding key={`${f.kind}:${f.title}`} finding={f} />)}</ul>
              )}
            </Card>
          </>
        )
      )}
    </div>
  );
};

export default JournalTab;
