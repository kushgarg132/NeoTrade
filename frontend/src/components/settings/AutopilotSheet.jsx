import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from '../doc/Doc';
import { Row, NumberField } from './Fields';
import api, { endpoints } from '../../utils/api';
import { cn } from '../../utils/cn';
import { formatDateTime } from '../../utils/formatters';

const LIMITS = [
  ['autopilot_capital', 'Capital', 'The most it may have invested at once (₹).'],
  ['autopilot_per_trade_cap', 'Per trade', 'Largest single order (₹).'],
  ['autopilot_max_trades_per_day', 'Trades per day', 'New positions it may open in a day.'],
  ['autopilot_daily_loss_limit', 'Daily loss limit', 'Stops new trades for the day once lost (₹).'],
];

/** The fenced autopilot on the AI account (backend/autopilot/). */
const AutopilotSheet = () => {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({});
  const [log, setLog] = useState([]);
  const [note, setNote] = useState(null);
  const [confirmLive, setConfirmLive] = useState(null); // typed text while arming live

  useEffect(() => {
    api.get(endpoints.settings.preferences).then((res) => {
      setPrefs(res.data);
      setDraft(Object.fromEntries(LIMITS.map(([key]) => [key, res.data[key]])));
    }).catch(() => setPrefs(null));
    api.get(endpoints.settings.autopilotLog).then((res) => setLog(res.data.rows)).catch(() => setLog([]));
  }, []);

  const save = (patch) => {
    setNote(null);
    return api.put(endpoints.settings.preferences, patch)
      .then((res) => setPrefs(res.data))
      .catch((err) => setNote(err?.response?.data?.detail || 'Could not save.'));
  };

  if (!prefs) return <Sheet title="Autopilot" className="mt-3 sm:mt-4"><Ruling rows={3} /></Sheet>;
  const aiBroker = Object.keys(prefs.broker_roles || {}).find((b) => prefs.broker_roles[b] === 'ai');

  return (
    <Sheet
      title="Autopilot"
      meta={prefs.autopilot_enabled ? (prefs.autopilot_live ? 'On · live' : 'On · paper') : 'Off'}
      className="mt-3 sm:mt-4"
    >
      <p className="text-sm text-[var(--ink-soft)]">
        Trades the AI account{aiBroker ? ` (${aiBroker.charAt(0).toUpperCase() + aiBroker.slice(1)})` : ''} by itself —
        AI chat ideas and engine proposals — inside these limits. NSE stocks only, market hours only. Every order
        and every refusal is sent to you on Telegram with a stop button.
      </p>
      {!aiBroker && (
        <p className="doc-meta normal-case text-[var(--loss)] mt-2">Set one broker as the AI account in Broker settings first.</p>
      )}
      <Row label="Autopilot" hint={prefs.autopilot_live ? 'Real orders on the AI account.' : 'Paper only for now.'}>
        <button
          type="button"
          role="switch"
          aria-checked={!!prefs.autopilot_enabled}
          disabled={!aiBroker}
          onClick={() => save({ autopilot_enabled: !prefs.autopilot_enabled })}
          className={cn('h-11 sm:h-8 px-4 text-xs border transition-colors disabled:opacity-40',
            prefs.autopilot_enabled ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]' : 'border-[var(--rule-strong)]')}
        >
          {prefs.autopilot_enabled ? 'On' : 'Off'}
        </button>
      </Row>
      <Row label="Mode" hint="Live sends real orders to the AI account's broker.">
        {prefs.autopilot_live ? (
          <button type="button" onClick={() => save({ autopilot_live: false })}
            className="h-11 sm:h-8 px-4 text-xs border border-[var(--loss)] text-[var(--loss)]">
            Live · switch to paper
          </button>
        ) : confirmLive === null ? (
          <button type="button" disabled={!aiBroker} onClick={() => setConfirmLive('')}
            className="h-11 sm:h-8 px-4 text-xs border border-[var(--rule-strong)] disabled:opacity-40">
            Paper · go live…
          </button>
        ) : (
          <span className="flex items-center gap-2">
            <input autoFocus value={confirmLive} onChange={(e) => setConfirmLive(e.target.value)}
              placeholder="Type LIVE" aria-label="Type LIVE to confirm real orders"
              className="w-24 bg-transparent border-b border-[var(--loss)] py-1 text-sm focus:outline-none" />
            <button type="button" disabled={confirmLive !== 'LIVE'}
              onClick={() => save({ autopilot_live: true }).then(() => setConfirmLive(null))}
              className="h-11 sm:h-8 px-3 text-xs bg-[var(--loss)] text-[var(--paper)] disabled:opacity-40">
              Go live
            </button>
            <button type="button" onClick={() => setConfirmLive(null)} className="text-xs text-[var(--ink-faint)]">Cancel</button>
          </span>
        )}
      </Row>
      {LIMITS.map(([key, label, hint]) => (
        <Row key={key} label={label} hint={hint}>
          <NumberField
            value={draft[key]}
            onChange={(value) => setDraft((d) => ({ ...d, [key]: value }))}
            onCommit={() => save({ [key]: Math.max(0, Number(draft[key]) || 0) })}
          />
        </Row>
      ))}
      {note && <p className="doc-meta normal-case text-[var(--loss)] mt-2">{note}</p>}
      <p className="field-label mt-4 mb-1">Recent activity</p>
      {log.length === 0 ? (
        <p className="doc-meta normal-case">Nothing yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--rule)]">
          {log.map((row, i) => (
            <li key={`${row.at}-${i}`} className="py-2 text-sm">
              <span className={cn('field-label mr-2', row.status === 'FILLED' ? 'text-[var(--gain)]' : 'text-[var(--loss)]')}>
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
  );
};

export default AutopilotSheet;
