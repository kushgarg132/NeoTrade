import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from '../doc/Doc';
import { Row, NumberField } from './Fields';
import api, { endpoints, getPreferences } from '../../utils/api';
import { cn } from '../../utils/cn';
import { formatDateTime } from '../../utils/formatters';

// One set for paper and live: Practice, live strategies, the autopilot and
// Watch my broker all read these fields.
const LIMITS = [
  ['account_size', 'Account size', 'What sizing risks up to 1% of per trade (₹).'],
  ['max_exposure', 'Max invested', 'The most open at once (₹).'],
  ['per_trade_cap', 'Per trade', 'Largest single order (₹). Halved while the market is risk-off.'],
  ['max_trades_per_day', 'Trades per day', 'New positions a day. 0 is off.'],
  ['daily_loss_limit', 'Daily loss limit', 'Stops new trades for the day once lost (₹).'],
];

/** The fenced autopilot on the AI account (backend/autopilot/). */
const AutopilotSheet = () => {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({});
  const [log, setLog] = useState([]);
  const [note, setNote] = useState(null);
  const [confirmLive, setConfirmLive] = useState(null); // typed text while arming live

  const [failed, setFailed] = useState(false);
  const loadPrefs = () =>
    getPreferences().then((res) => {
      setPrefs(res.data);
      setDraft(Object.fromEntries(LIMITS.map(([key]) => [key, res.data[key]])));
    }).catch(() => setFailed(true));
  useEffect(() => {
    loadPrefs();
    api.get(endpoints.settings.autopilotLog).then((res) => setLog(res.data.rows)).catch(() => setLog([]));
  }, []);

  const save = (patch) => {
    setNote(null);
    return api.put(endpoints.settings.preferences, patch)
      .then((res) => setPrefs(res.data))
      .catch((err) => setNote(err?.response?.data?.detail || 'Could not save.'));
  };

  if (failed) {
    return (
      <Sheet title="Autopilot" className="mt-3 sm:mt-4">
        <p className="text-sm">
          Couldn't load the autopilot's settings.{' '}
          <button type="button" className="underline min-h-11" onClick={() => { setFailed(false); loadPrefs(); }}>Retry</button>
        </p>
      </Sheet>
    );
  }
  if (!prefs) return <Sheet title="Autopilot" className="mt-3 sm:mt-4"><Ruling rows={3} /></Sheet>;
  const aiBroker = Object.keys(prefs.broker_roles || {}).find((b) => prefs.broker_roles[b] === 'ai');

  return (
    <>
    <Sheet title="Trading limits" meta="Paper and live" className="mt-3 sm:mt-4">
      <p className="text-sm text-[var(--ink-soft)]">
        One set for everything: Practice, live strategies, the autopilot, and Watch my broker on your own account.
      </p>
      {LIMITS.map(([key, label, hint]) => (
        <Row key={key} label={label} hint={hint}>
          <NumberField
            value={draft[key]}
            onChange={(value) => setDraft((d) => ({ ...d, [key]: value }))}
            onCommit={() => {
              const value = Math.max(0, Number(draft[key]) || 0);
              if (key === 'daily_loss_limit' && value === 0) {
                setDraft((d) => ({ ...d, [key]: prefs[key] }));
                return setNote('Turn the loss limit off in Settings › Safety, which asks you to confirm.');
              }
              return save({ [key]: value });
            }}
          />
        </Row>
      ))}
    </Sheet>
    <Sheet
      title="Autopilot"
      meta={prefs.autopilot_enabled ? (prefs.autopilot_live ? 'On · live' : 'On · paper') : 'Off'}
      className="mt-3 sm:mt-4"
    >
      <p className="text-sm text-[var(--ink-soft)]">
        Acts for the AI account{aiBroker ? ` (${aiBroker.charAt(0).toUpperCase() + aiBroker.slice(1)})` : ''} without
        asking you: it takes the Practice engine's proposals and AI chat ideas and places them, inside the
        trading limits above. NSE stocks only, market hours only. Every order and every refusal is sent to you on
        Telegram with a stop button.
      </p>
      {!aiBroker && (
        <p className="doc-meta normal-case text-[var(--loss)] mt-2">Set one broker as the AI account in Broker settings first.</p>
      )}
      <Row
        label="Autopilot"
        hint={!prefs.autopilot_enabled ? 'Off: places nothing.'
          : prefs.autopilot_live ? 'Live: real orders on the AI account, only from strategies that passed their backtest and their paper record. Other proposals wait for you.'
          : 'Paper: fills in your Practice book, tagged autopilot. Nothing sent to the broker.'}
      >
        {confirmLive === null ? (
          <span className="inline-flex" role="radiogroup" aria-label="Autopilot mode">
            {[
              ['off', 'Off', !prefs.autopilot_enabled, () => save({ autopilot_enabled: false, autopilot_live: false })],
              ['paper', 'Paper', prefs.autopilot_enabled && !prefs.autopilot_live, () => save({ autopilot_enabled: true, autopilot_live: false })],
              ['live', 'Live', prefs.autopilot_enabled && prefs.autopilot_live, () => setConfirmLive('')],
            ].map(([key, label, active, choose]) => (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={!aiBroker && key !== 'off'}
                onClick={() => !active && choose()}
                className={cn('h-11 sm:h-8 px-4 text-xs border -ml-px first:ml-0 transition-colors disabled:opacity-40',
                  !active && 'border-[var(--rule-strong)]',
                  active && key !== 'live' && 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]',
                  active && key === 'live' && 'bg-[var(--loss)] text-[var(--paper)] border-[var(--loss)]')}
              >
                {label}
              </button>
            ))}
          </span>
        ) : (
          <span className="flex items-center gap-2">
            <input autoFocus value={confirmLive} onChange={(e) => setConfirmLive(e.target.value)}
              placeholder="Type LIVE" aria-label="Type LIVE to confirm real orders"
              className="w-24 bg-transparent border-b border-[var(--loss)] py-1 text-sm focus:outline-none" />
            <button type="button" disabled={confirmLive !== 'LIVE'}
              onClick={() => save({ autopilot_enabled: true, autopilot_live: true }).then(() => setConfirmLive(null))}
              className="h-11 sm:h-8 px-3 text-xs bg-[var(--loss)] text-[var(--paper)] disabled:opacity-40">
              Go live
            </button>
            <button type="button" onClick={() => setConfirmLive(null)} className="text-xs text-[var(--ink-faint)]">Cancel</button>
          </span>
        )}
      </Row>
      {prefs.autopilot_enabled && <Row
        label="Trade on news"
        hint="Buys a proposal from material news at once instead of waiting for the morning pass. At most 3 a day, none while the market is risk-off. Sells on bad news are only logged for now."
      >
        <button
          type="button"
          role="switch"
          aria-checked={!!prefs.autopilot_news}
          onClick={() => save({ autopilot_news: !prefs.autopilot_news })}
          className={cn('h-11 sm:h-8 px-4 text-xs border transition-colors disabled:opacity-40',
            prefs.autopilot_news ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]' : 'border-[var(--rule-strong)]')}
        >
          {prefs.autopilot_news ? 'On' : 'Off'}
        </button>
      </Row>}
      {note && <p className="doc-meta normal-case text-[var(--loss)] mt-2">{note}</p>}
      <p className="field-label mt-4 mb-1">Recent activity</p>
      {log.length === 0 ? (
        <p className="doc-meta normal-case">Nothing yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--rule)]">
          {log.map((row, i) => (
            <li key={`${row.at}-${i}`} className="py-2 text-sm">
              <span className={cn('field-label mr-2', row.status === 'FILLED' ? 'text-[var(--gain)]' : row.status === 'SENT' ? 'text-[var(--ink-soft)]' : 'text-[var(--loss)]')}>
                {row.status}
              </span>
              {row.side} {row.quantity} {row.symbol}
              <span className="doc-meta normal-case"> · {row.source} · {formatDateTime(row.at)}</span>
              {row.reason && row.status !== 'FILLED' && <p className="doc-meta normal-case">{row.reason}</p>}
            </li>
          ))}
        </ul>
      )}
    </Sheet>
    </>
  );
};

export default AutopilotSheet;
