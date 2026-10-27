import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Ruling, Button } from '../settings/Panel';
import api, { endpoints, getPreferences } from '../../utils/api';
import { Row, NumberField, Toggle, Segmented } from '../settings/Fields';
import { formatCurrency } from '../../utils/formatters';
import useSchedule from '../../hooks/useSchedule';

const GUARD_FIELDS = [
  'max_trades_per_day', 'cooldown_after_losses', 'cooldown_minutes', 'daily_loss_limit',
  'max_option_trades_per_day', 'max_option_lots', 'no_buy_before_results_days',
];

const GuardrailsSheet = () => {
  const { t } = useSchedule();
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({});
  const [note, setNote] = useState(null);

  useEffect(() => {
    getPreferences()
      .then((res) => {
        setPrefs(res.data);
        setDraft(Object.fromEntries(GUARD_FIELDS.map((key) => [key, res.data[key]])));
      })
      .catch(() => setPrefs(null));
  }, []);

  const save = (patch) => api.put(endpoints.settings.preferences, patch).then((res) => setPrefs(res.data));
  const [confirmOff, setConfirmOff] = useState(false);

  // An empty or invalid field restores the saved value instead of saving 0
  // (0 means "off" for every guardrail); a refused save says why and resets.
  const commit = (key, value) => {
    const restore = () => setDraft((d) => ({ ...d, [key]: prefs[key] }));
    if (String(draft[key]).trim() === '' || !Number.isFinite(value) || value < 0) return restore();
    if (value === prefs[key]) return undefined;
    // 0 turns the daily loss limit -- and with it the kill-switch -- off: never by a cleared field.
    if (key === 'daily_loss_limit' && value === 0) return setConfirmOff(true);
    setNote(null);
    return save({ [key]: value }).catch((err) => {
      setNote(err?.response?.data?.detail || 'That value was not saved.');
      restore();
    });
  };

  if (!prefs) {
    return (
      <Sheet title="Guardrails">
        <Ruling rows={3} />
      </Sheet>
    );
  }

  const numberRow = (key, label, hint) => (
    <Row label={label} hint={hint}>
      <NumberField
        value={draft[key]}
        onChange={(value) => setDraft((d) => ({ ...d, [key]: value }))}
        onCommit={() => commit(key, Math.round(Number(draft[key])))}
        zeroIsOff
      />
    </Row>
  );

  return (
    <Sheet
      title="Guardrails"
      meta={
        prefs.guardrails_enabled
          ? prefs.auto_square_off === 'live'
            ? 'Watching · square-off live'
            : 'Watching'
          : 'Off'
      }
    >
      <p className="text-[13px] text-[var(--text-muted)] pb-3 border-b border-[var(--border)]">
        Limits you set for yourself. NeoTrade checks them against your broker every minute during the
        session and alerts you when one is crossed. It cannot stop an order you place in your broker's
        own app.
      </p>

      <Row label="Watch my broker" hint={`Checks every connected broker from ${t.monitor_open} to ${t.monitor_close} IST.`}>
        <Toggle on={prefs.guardrails_enabled} label="Watch my broker" onClick={() => save({ guardrails_enabled: !prefs.guardrails_enabled })} />
      </Row>

      <Row
        label="Daily loss limit"
        hint="Checked against your broker's own day P&L. Reaching it also trips the engine's kill-switch for the day. Shared with the AI account (AI › Settings › Trading limits)."
      >
        <NumberField
          value={draft.daily_loss_limit}
          onChange={(value) => {
            setConfirmOff(false);
            setDraft((d) => ({ ...d, daily_loss_limit: value }));
          }}
          onCommit={() => commit('daily_loss_limit', Number(draft.daily_loss_limit))}
          zeroIsOff
        />
      </Row>
      {confirmOff && (
        <div role="alert" className="py-2 flex flex-wrap items-center justify-between gap-2 text-[14px] text-[var(--loss)]">
          <span>0 turns off the daily loss limit and the engine's kill-switch.</span>
          <span className="inline-flex gap-2">
            <button
              type="button"
              className="min-h-11 px-3 rounded-[12px] border border-[var(--border)] text-[var(--text)]"
              onClick={() => {
                setConfirmOff(false);
                setDraft((d) => ({ ...d, daily_loss_limit: prefs.daily_loss_limit }));
              }}
            >
              Keep {formatCurrency(prefs.daily_loss_limit)}
            </button>
            <button
              type="button"
              className="min-h-11 px-3 rounded-[12px] border border-[var(--loss)]"
              onClick={() => {
                setConfirmOff(false);
                save({ daily_loss_limit: 0 }).catch((err) => setNote(err?.response?.data?.detail || 'That value was not saved.'));
              }}
            >
              Turn off
            </button>
          </span>
        </div>
      )}

      {numberRow('max_trades_per_day', 'Trades per day', 'Alert when you open more than this; the autopilot opens no more. Shared with AI › Settings › Trading limits. 0 is off.')}
      {numberRow('cooldown_after_losses', 'Cooldown after losses in a row', 'Start a cooldown after this many losses in a row. 0 is off.')}
      {numberRow('cooldown_minutes', 'Cooldown length, minutes', 'Any trade opened inside it is flagged.')}
      {numberRow('max_option_trades_per_day', 'Options trades per day', 'Alert when you open more options trades than this. 0 is off.')}
      {numberRow('max_option_lots', 'Lots per options trade', 'Alert when one options position is bigger than this many lots. Needs Kite connected for lot sizes. 0 is off.')}
      {numberRow('no_buy_before_results_days', 'No buys before results, days', 'Refuse a buy from NeoTrade, and alert on one from your broker app, when the stock reports results within this many days. 0 is off.')}

      <Row
        label="Warn on unhedged option selling"
        hint="Alert when you sell an option with no bought option on the same underlying open to cap the loss. A sold option's loss has no fixed limit."
      >
        <Toggle on={prefs.warn_naked_options} label="Warn on unhedged option selling" onClick={() => save({ warn_naked_options: !prefs.warn_naked_options })} />
      </Row>

      <Row
        label="Square off at the loss limit"
        hint={
          prefs.auto_square_off === 'live'
            ? 'Live: when the daily loss limit is hit, NeoTrade places market orders to close your NSE intraday (MIS) positions, once a day. Delivery and F&O positions are never touched.'
            : 'Preview alerts you with the exact exit orders it would place, without sending them. Live sends them. Only NSE intraday (MIS) positions, once a day.'
        }
      >
        <Segmented
          label="Square off at the loss limit"
          options={[['off', 'Off'], ['preview', 'Preview'], ['live', 'Live']]}
          value={prefs.auto_square_off}
          dangerValue="live"
          onChange={(value) => {
            if (value === prefs.auto_square_off) return;
            if (
              value === 'live' &&
              !window.confirm(
                'Live square-off places real market orders on your broker account, without asking, when your daily loss limit is hit. Turn it on?'
              )
            )
              return;
            save({ auto_square_off: value });
          }}
        />
      </Row>

      <Row
        label="News alerts"
        hint="Material news on the names you follow, as a toast here and on Telegram when linked. A market-wide shock reaches anyone holding something."
      >
        <Segmented
          label="News alerts"
          options={[['held', 'Holdings'], ['held+watched', '+ Watchlist'], ['all', 'All'], ['off', 'Off']]}
          value={prefs.news_alerts || 'held'}
          onChange={(value) => value !== prefs.news_alerts && save({ news_alerts: value })}
        />
      </Row>
      {note && <p className="text-[13px] text-[var(--text-muted)] pt-2">{note}</p>}
    </Sheet>
  );
};

export default GuardrailsSheet;
