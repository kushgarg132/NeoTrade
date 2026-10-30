import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from './Panel';
import { Row, NumberField, Toggle, Segmented } from './Fields';
import api, { endpoints, getPreferences } from '../../utils/api';
import { Link } from 'react-router-dom';
import EngineSwitches from './EngineSwitches';
import { useAuth } from '../../context/AuthContext';

// One set for paper and live: Practice, live strategies, the autopilot and
// Watch my broker all read these fields.
const LIMITS = [
  ['account_size', 'Account size', 'What sizing risks up to 1% of per trade.', '₹'],
  ['max_exposure', 'Max invested', 'The most open at once.', '₹'],
  ['per_trade_cap', 'Per trade', 'Largest single order. Halved while the market is risk-off.', '₹'],
  ['max_trades_per_day', 'Trades per day', 'New positions a day. 0 is off.'],
  ['daily_loss_limit', 'Daily loss limit', 'Stops new trades for the day once lost.', '₹'],
];

/** The fenced autopilot on the AI account (backend/autopilot/), then the
 * engine that feeds it, then the limits both trade inside. */
const AutopilotSheet = () => {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({});
  const [note, setNote] = useState(null);
  const [confirmLive, setConfirmLive] = useState(null); // typed text while arming live

  const [failed, setFailed] = useState(false);
  const isAdmin = useAuth().user?.role === 'admin';
  const loadPrefs = () =>
    getPreferences().then((res) => {
      setPrefs(res.data);
      setDraft(Object.fromEntries(LIMITS.map(([key]) => [key, res.data[key]])));
    }).catch(() => setFailed(true));
  useEffect(() => {
    loadPrefs();
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
    <Sheet
      title="Autopilot"
      meta={prefs.autopilot_enabled ? (prefs.autopilot_live ? 'On · live' : 'On · paper') : 'Off'}
      className="mt-3 sm:mt-4"
    >
      <p className="text-sm text-[var(--text-muted)]">
        Acts for the AI account{aiBroker ? ` (${aiBroker.charAt(0).toUpperCase() + aiBroker.slice(1)})` : ''} without
        asking you: it takes the engine's proposals and AI chat ideas and places them, inside the
        trading limits below. NSE stocks only, market hours only. Every order and every refusal is sent to you on
        Telegram with a stop button.
      </p>
      {!aiBroker && (
        <p className="text-[13px] text-[var(--loss)] mt-2">Set one broker as the AI account in Broker settings first.</p>
      )}
      <Row
        label="Autopilot"
        hint={!prefs.autopilot_enabled ? 'Off: places nothing.'
          : prefs.autopilot_live ? 'Live: real orders on the AI account, only from strategies that passed their backtest and their paper record. Others stay on paper.'
          : 'Paper: fills in the AI account’s paper book. Nothing sent to the broker.'}
      >
        {confirmLive === null ? (
          <Segmented
            label="Autopilot mode"
            options={[['off', 'Off'], ['paper', 'Paper'], ['live', 'Live']]}
            value={!prefs.autopilot_enabled ? 'off' : prefs.autopilot_live ? 'live' : 'paper'}
            dangerValue="live"
            disabled={(v) => !aiBroker && v !== 'off'}
            onChange={(v) => {
              const now = !prefs.autopilot_enabled ? 'off' : prefs.autopilot_live ? 'live' : 'paper';
              if (v === now) return;
              if (v === 'live') setConfirmLive('');
              else save({ autopilot_enabled: v === 'paper', autopilot_live: false });
            }}
          />
        ) : (
          <span className="flex items-center gap-2">
            <input autoFocus value={confirmLive} onChange={(e) => setConfirmLive(e.target.value)}
              placeholder="Type LIVE" aria-label="Type LIVE to confirm real orders"
              className="w-28 min-h-11 rounded-[12px] border border-[var(--loss)] bg-[var(--surface-2)] px-3 text-[15px] focus:outline-none" />
            <button type="button" disabled={confirmLive !== 'LIVE'}
              onClick={() => save({ autopilot_enabled: true, autopilot_live: true }).then(() => setConfirmLive(null))}
              className="tap min-h-11 px-4 rounded-[12px] bg-[var(--loss)] text-[var(--accent-ink)] text-[14px] font-semibold disabled:opacity-40">
              Go live
            </button>
            <button type="button" onClick={() => setConfirmLive(null)} className="min-h-11 px-2 text-[14px] text-[var(--text-muted)]">Cancel</button>
          </span>
        )}
      </Row>
      {prefs.autopilot_enabled && <Row
        label="Trade on news"
        hint="Buys a proposal from material news at once instead of waiting for the morning pass. At most 3 a day, none while the market is risk-off. Sells on bad news are only logged for now."
      >
        <Toggle on={prefs.autopilot_news} label="Trade on news" onClick={() => save({ autopilot_news: !prefs.autopilot_news })} />
      </Row>}
      {isAdmin && <Row
        label="Picks with real money"
        hint="Picks trade the AI account on paper as their forward record. Real money waits until 100 picks are scored, their calibration is within 5 points and they beat the Nifty after charges; then the owner turns on picks_live."
      >
        <Toggle on={false} label="Picks with real money" disabled />
      </Row>}
      {note && <p className="text-[13px] text-[var(--loss)] mt-2">{note}</p>}
      <Link to="/ai/activity" className="inline-flex items-center min-h-11 mt-1 text-[14px] font-medium text-[var(--accent)] hover:underline">What it did ›</Link>
    </Sheet>
    <EngineSwitches prefs={prefs} save={save} />
    <Sheet title="Trading limits" meta="Paper and live" className="mt-3 sm:mt-4">
      <p className="text-sm text-[var(--text-muted)]">
        One set for everything: the AI account (paper and live), and Watch my broker on your own account.
      </p>
      {LIMITS.map(([key, label, hint, prefix]) => (
        <Row key={key} label={label} hint={hint}>
          <NumberField
            label={label}
            prefix={prefix}
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
    </>
  );
};

export default AutopilotSheet;
