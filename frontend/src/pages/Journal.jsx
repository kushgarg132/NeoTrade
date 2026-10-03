import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import Layout from '../components/Layout';
import GuardrailAlerts from '../components/journal/GuardrailAlerts';
import MonthGrid from '../components/journal/MonthGrid';
import { monthKey, shiftMonth, monthLabel, todayIst } from '../utils/months';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine, Scrip } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import {
  formatCurrency,
  formatQuantity,
  formatPercent,
  formatSigned,
  formatDateTime,
} from '../utils/formatters';

/**
 * The journal: every fill from the user's own broker, grouped into round
 * trips, laid out as a month of days. It reports what the user did — it never
 * says what they should do next.
 */

const BUTTON =
  'px-3 py-1.5 min-h-9 border border-[var(--rule-strong)] font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] text-[var(--ink-soft)] hover:text-[var(--ink)] hover:border-[var(--ink)] transition-colors disabled:opacity-50';


const Finding = ({ finding }) => (
  <li className="py-3 border-b border-[var(--rule)] last:border-b-0">
    <div className="flex items-baseline justify-between gap-3">
      <p className="text-sm text-[var(--ink)]">{finding.title}</p>
      <Money value={finding.pnl} />
    </div>
    <p className="doc-meta normal-case mt-1">
      {finding.trips} trades · win rate {formatPercent(finding.win_rate * 100)} against{' '}
      {formatPercent(finding.baseline_win_rate * 100)} on the rest · {formatSigned(finding.avg_pnl)} a trade
      against {formatSigned(finding.baseline_avg_pnl)}
    </p>
    {finding.note && <p className="doc-meta normal-case mt-1 text-[var(--ink-soft)]">{finding.note}</p>}
  </li>
);

const NoteEditor = ({ trip, onSaved }) => {
  const [note, setNote] = useState(trip.note || '');
  const [tags, setTags] = useState((trip.tags || []).join(', '));
  const [busy, setBusy] = useState(false);

  const save = () => {
    setBusy(true);
    api
      .put(endpoints.journal.note(trip.id), {
        note,
        tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean),
      })
      .then((res) => onSaved(trip.id, res.data))
      .finally(() => setBusy(false));
  };

  return (
    <div className="space-y-3 py-3">
      <p className="doc-meta normal-case">
        Opened {formatDateTime(trip.opened_at)}
        {trip.closed_at && ` · closed ${formatDateTime(trip.closed_at)}`} · {trip.broker}
      </p>
      <label className="block">
        <span className="field-label block mb-1">Note</span>
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={3}
          maxLength={5000}
          placeholder="Why you took it, what you saw, how it went"
          className="w-full bg-transparent border border-[var(--rule-strong)] p-2 text-sm focus:outline-none focus:border-[var(--stamp)]"
        />
      </label>
      <label className="block">
        <span className="field-label block mb-1">Tags, comma separated</span>
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="breakout, fomo, planned"
          autoComplete="off"
          className="w-full bg-transparent border-b border-[var(--rule-strong)] py-1.5 text-sm focus:outline-none focus:border-[var(--stamp)]"
        />
      </label>
      <button type="button" className={BUTTON} onClick={save} disabled={busy}>
        {busy ? 'Saving' : 'Save note'}
      </button>
    </div>
  );
};

const Journal = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [month, setMonth] = useState(null);
  const [selectedDay, setSelectedDay] = useState(null);
  const [openTrip, setOpenTrip] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const fileInput = useRef(null);
  const load = () =>
    api
      .get(endpoints.journal.get)
      .then((res) => {
        setData(res.data);
        setError(null);
        setMonth((current) => {
          if (current) return current;
          const last = res.data.calendar[res.data.calendar.length - 1];
          return monthKey(last ? last.day : todayIst());
        });
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the journal'));

  useEffect(() => {
    load();
  }, []);

  const run = (request, describe) => {
    setBusy(true);
    setMessage(null);
    request()
      .then((res) => {
        setMessage(describe(res.data));
        return load();
      })
      .catch((err) => setMessage(err?.response?.data?.detail || 'That did not work'))
      .finally(() => setBusy(false));
  };

  const sync = () =>
    run(
      () => api.post(endpoints.journal.sync),
      (result) =>
        result.brokers.length === 0 && result.failed.length === 0
          ? 'No broker is connected. Connect one in Settings, or import a Console tradebook.'
          : `${result.imported} new fill${result.imported === 1 ? '' : 's'} from ${result.brokers.join(', ') || 'no broker'}` +
            (result.failed.length ? `. ${result.failed.join(', ')} did not respond.` : '.')
    );

  const importUpstox = () =>
    run(
      () => api.post(endpoints.journal.importUpstox, { days: 365 }),
      (result) =>
        `${result.imported} fill${result.imported === 1 ? '' : 's'} imported from Upstox's last year` +
        (result.skipped_synced_days ? `; ${result.skipped_synced_days} day(s) already synced were left as they were` : '') +
        '. History has dates but no times, so each day\'s fills are shown at 09:15.'
    );

  const importCsv = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    file.text().then((csv) =>
      run(
        () => api.post(endpoints.journal.importConsole, { csv }),
        (result) =>
          `${result.imported} fill${result.imported === 1 ? '' : 's'} imported` +
          (result.duplicates ? `, ${result.duplicates} already in the journal` : '') +
          (result.skipped ? `, ${result.skipped} unreadable row${result.skipped === 1 ? '' : 's'} skipped` : '') +
          '.'
      )
    );
  };

  const onNoteSaved = (id, saved) =>
    setData((current) => ({
      ...current,
      round_trips: current.round_trips.map((trip) => (trip.id === id ? { ...trip, ...saved } : trip)),
    }));

  const byDay = useMemo(
    () => Object.fromEntries((data?.calendar || []).map((row) => [row.day, row])),
    [data]
  );

  const monthTotal = useMemo(
    () =>
      (data?.calendar || [])
        .filter((row) => month && monthKey(row.day) === month)
        .reduce((total, row) => ({ pnl: total.pnl + row.pnl, trips: total.trips + row.trips }), {
          pnl: 0,
          trips: 0,
        }),
    [data, month]
  );

  const trips = useMemo(() => {
    const all = data?.round_trips || [];
    return selectedDay ? all.filter((trip) => trip.day === selectedDay) : all.slice(0, 50);
  }, [data, selectedDay]);

  const actions = (
    <div className="flex gap-2">
      <button type="button" className={BUTTON} onClick={sync} disabled={busy}>
        Sync today
      </button>
      <button type="button" className={BUTTON} onClick={() => fileInput.current?.click()} disabled={busy}>
        Import CSV
      </button>
      {data?.brokers_connected?.includes('upstox') && (
        <button type="button" className={BUTTON} onClick={importUpstox} disabled={busy}>
          Import Upstox history
        </button>
      )}
      <input ref={fileInput} type="file" accept=".csv,text/csv" className="hidden" onChange={importCsv} />
    </div>
  );

  if (!data && !error) {
    return (
      <Layout>
        <Sheet title="Journal">
          <Ruling rows={6} />
        </Sheet>
      </Layout>
    );
  }

  const summary = data?.summary;
  const empty = !data || data.round_trips.length === 0;

  return (
    <Layout>
      <div className="space-y-4">
        <GuardrailAlerts />

        <Sheet
          title="Journal"
          meta={summary ? `${summary.trips} closed` : undefined}
          actions={actions}
        >
          {message && <p className="doc-meta normal-case mb-3">{message}</p>}
          {error ? (
            <Empty title="Could not load the journal" detail={error} />
          ) : empty ? (
            <Empty
              title="No trades in the journal yet"
              detail="Sync pulls today's fills from every connected broker, and it runs on its own after the close each day. For older history, download your tradebook from Zerodha Console (Reports → Tradebook) and import the CSV."
            />
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <button
                  type="button"
                  className="p-2 min-h-9 text-[var(--ink-soft)] hover:text-[var(--ink)]"
                  onClick={() => {
                    setMonth(shiftMonth(month, -1));
                    setSelectedDay(null);
                  }}
                  aria-label="Previous month"
                >
                  <ChevronLeft size={16} />
                </button>
                <span className="field-label text-[var(--ink)]">{monthLabel(month)}</span>
                <button
                  type="button"
                  className="p-2 min-h-9 text-[var(--ink-soft)] hover:text-[var(--ink)]"
                  onClick={() => {
                    setMonth(shiftMonth(month, 1));
                    setSelectedDay(null);
                  }}
                  aria-label="Next month"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
              <MonthGrid month={month} byDay={byDay} selected={selectedDay} onSelect={setSelectedDay} />
              <NetLine label={`${monthLabel(month)}, ${monthTotal.trips} closed`}>
                <Money value={monthTotal.pnl} size="lg" />
              </NetLine>
              <div className="grid grid-cols-2 gap-4 mt-4">
                <div>
                  <p className="field-label mb-1">All time, gross</p>
                  <Money value={summary.pnl} />
                </div>
                <div>
                  <p className="field-label mb-1">Strike rate</p>
                  <span className="figure-md text-base">
                    {summary.trips ? formatPercent((summary.wins / summary.trips) * 100) : '—'}
                  </span>
                </div>
              </div>
              {/* Stocks, options and futures apart: a total hides which one
                  is carrying the book and which is sinking it. */}
              {summary.by_kind && Object.keys(summary.by_kind).length > 1 && (
                <div className="grid sm:grid-cols-3 gap-x-4 gap-y-2 mt-4 pt-3 border-t border-[var(--rule)]">
                  {['stocks', 'options', 'futures'].filter((k) => summary.by_kind[k]).map((kind) => (
                    <div key={kind} className="min-w-0 flex items-baseline justify-between gap-3 sm:block">
                      <p className="field-label sm:mb-1">
                        {kind} · {summary.by_kind[kind].trips}
                      </p>
                      <Money value={summary.by_kind[kind].pnl} />
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </Sheet>

        {!empty && (
          <Sheet title="Your patterns" meta="Your own trades, gross">
            {data.insights.length === 0 ? (
              <Empty
                title="Not enough trades to see a pattern"
                detail="A pattern is only shown once it covers at least 5 closed trades. Tags you add to trades are counted too."
              />
            ) : (
              <ul>
                {data.insights.map((finding) => (
                  <Finding key={`${finding.kind}:${finding.title}`} finding={finding} />
                ))}
              </ul>
            )}
          </Sheet>
        )}

        {!empty && (
          <Sheet
            title={selectedDay ? `Trades closed ${selectedDay}` : 'Recent round trips'}
            meta="Gross of charges"
            actions={
              selectedDay && (
                <button type="button" className={BUTTON} onClick={() => setSelectedDay(null)}>
                  All
                </button>
              )
            }
          >
            <Statement
              columns={[
                { key: 'scrip', label: 'Scrip' },
                { key: 'qty', label: 'Qty', align: 'right' },
                { key: 'entry', label: 'Entry', align: 'right' },
                { key: 'exit', label: 'Exit', align: 'right' },
                { key: 'pnl', label: 'P&L', align: 'right' },
              ]}
            >
              {trips.map((trip) => (
                <React.Fragment key={trip.id}>
                  <Row
                    className="cursor-pointer hover:bg-[var(--paper-sunk)]"
                    onClick={() => setOpenTrip(openTrip === trip.id ? null : trip.id)}
                    aria-expanded={openTrip === trip.id}
                  >
                    <Cell>
                      <Scrip symbol={trip.symbol} />
                      <span className="doc-meta ml-2">{trip.direction === 'SHORT' ? 'Short' : 'Long'}</span>
                      {trip.kind && trip.kind !== 'STOCK' && (
                        <span className="ml-2 px-1 border border-[var(--rule-strong)] field-label text-[0.625rem]">
                          {trip.kind === 'FUTURE' ? 'FUT' : trip.kind}
                        </span>
                      )}
                      {trip.tags?.length > 0 && (
                        <span className="doc-meta normal-case block">{trip.tags.join(' · ')}</span>
                      )}
                    </Cell>
                    <Cell align="right" mono>
                      {formatQuantity(trip.quantity)}
                    </Cell>
                    <Cell align="right" mono>
                      {formatCurrency(trip.entry_price)}
                    </Cell>
                    <Cell align="right" mono>
                      {trip.exit_price === null ? 'Open' : formatCurrency(trip.exit_price)}
                    </Cell>
                    <Cell align="right">
                      <Money value={trip.pnl} />
                    </Cell>
                  </Row>
                  {openTrip === trip.id && (
                    <tr>
                      <td colSpan={5}>
                        <NoteEditor trip={trip} onSaved={onNoteSaved} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </Statement>
          </Sheet>
        )}
      </div>
    </Layout>
  );
};

export default Journal;
