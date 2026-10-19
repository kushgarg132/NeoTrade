import React from 'react';
import { Link } from 'react-router-dom';
import { Sheet } from '../doc/Doc';
import { Row } from './Fields';
import { cn } from '../../utils/cn';
import useSchedule from '../../hooks/useSchedule';

/**
 * What the strategy engine does by itself, under the autopilot (AI ›
 * Settings). The autopilot trades the 4 PM scan's proposals and acts in the
 * long-term pass, so while it is on both run regardless of their own
 * switches (backend/prefs.py::scan_enabled_users, engine/autorun.py::tick);
 * here they show as kept on. Intraday paper is independent. Limits and
 * per-strategy live switches stay in Lab › Autopilot limits.
 */

const SWITCH =
  'px-3 py-1 border text-[13px] font-semibold transition-colors';

const EngineSwitches = ({ prefs, save }) => {
  const { t, raw } = useSchedule();
  const autopilot = Boolean(prefs.autopilot_enabled);
  const on = (key, byAutopilot) => (byAutopilot && autopilot) || Boolean(prefs[key]);

  const switchRow = (key, label, hint, byAutopilot = false) => (
    <Row label={label} hint={byAutopilot && autopilot ? `Kept on while the autopilot is on. ${hint}` : hint}>
      {byAutopilot && autopilot ? (
        <span className={cn(SWITCH, 'text-[var(--text-muted)] border-[var(--border)]')}>Autopilot</span>
      ) : (
        <button
          type="button"
          role="switch"
          aria-checked={Boolean(prefs[key])}
          onClick={() => save({ [key]: !prefs[key] })}
          className={cn(
            SWITCH,
            prefs[key]
              ? 'bg-[var(--text)] text-[var(--surface)] border-[var(--text)]'
              : 'text-[var(--text-muted)] border-[var(--border)]'
          )}
        >
          {prefs[key] ? 'On' : 'Off'}
        </button>
      )}
    </Row>
  );

  return (
    <Sheet
      title="Engine"
      meta={`${[on('auto_paper_intraday'), on('scan_enabled', true), on('auto_paper_longterm', true)].filter(Boolean).length} of 3 on`}
      className="mt-3 sm:mt-4"
    >
      <p className="text-sm text-[var(--text-muted)]">
        {autopilot
          ? 'Feeds the autopilot: the scan and the long-term pass stay on while it is on. Only intraday paper is your call.'
          : <>The strategy engine on its own. Ideas from proven strategies wait for you in{' '}
              <Link to="/portfolio" className="underline">Portfolio</Link>; turn the autopilot on and it paper-trades the rest.</>}
      </p>
      {switchRow(
        'auto_paper_intraday',
        'Paper-trade intraday every session (experimental)',
        `Experimental: the intraday strategies lose money after charges in every backtest so far, so this is for watching them, not for results. Starts an intraday paper run at ${t.session_open} IST each weekday and stops it at ${t.session_close}, with positions squared off at ${t.square_off}. It restarts itself after an interruption; stop it on AI › Overview and it stays off for the rest of that day.`
      )}
      {switchRow(
        'scan_enabled',
        'Daily long-term scan',
        `Runs after the close at ${t.daily_pass} IST over your ${prefs.universe.length} scrip and files long-term proposals.`,
        true
      )}
      {switchRow(
        'auto_paper_longterm',
        'Long-term paper book',
        `Runs the factor portfolio on paper with its own ₹3 lakh book: the top Nifty 200 stocks by momentum and low volatility, rebalanced at ${t.morning} on the first trading day of each month, in a liquid ETF whenever the Nifty is below its 200-day average. Also sells an approved long-term paper position at its stop or target (checked every ${raw.exit_check_minutes} minutes in session) and sends a Telegram digest.`,
        true
      )}
      <p className="pt-3 text-[13px] text-[var(--text-muted)]">
        Which strategies may trade real money:{' '}
        <Link to="/lab/limits" className="underline">Lab › Autopilot limits</Link>.
      </p>
    </Sheet>
  );
};

export default EngineSwitches;
