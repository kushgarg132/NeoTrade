import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Ruling } from '../doc/Doc';
import { Row } from './Fields';
import api, { endpoints, getPreferences } from '../../utils/api';
import { cn } from '../../utils/cn';

/**
 * What the strategy engine does by itself: the daily paper runs and the
 * 4:00 PM scan. Beside the autopilot on AI › Autopilot, since together they
 * decide what happens without a tap. Limits and per-strategy live switches
 * stay in Practice › Setup.
 */

const SWITCH =
  'px-3 py-1 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors';

const EngineSwitches = () => {
  const [prefs, setPrefs] = useState(null);

  useEffect(() => {
    getPreferences().then((res) => setPrefs(res.data)).catch(() => setPrefs(null));
  }, []);

  const save = async (patch) => {
    const res = await api.put(endpoints.settings.preferences, patch);
    setPrefs(res.data);
  };

  if (!prefs) {
    return (
      <Sheet title="Engine">
        <Ruling rows={3} />
      </Sheet>
    );
  }

  const switchRow = (key, label, hint) => (
    <Row label={label} hint={hint}>
      <button
        type="button"
        role="switch"
        aria-checked={Boolean(prefs[key])}
        onClick={() => save({ [key]: !prefs[key] })}
        className={cn(
          SWITCH,
          prefs[key]
            ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
            : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
        )}
      >
        {prefs[key] ? 'On' : 'Off'}
      </button>
    </Row>
  );

  return (
    <Sheet
      title="Engine"
      meta={[prefs.auto_paper_intraday, prefs.auto_paper_longterm, prefs.scan_enabled].filter(Boolean).length + ' of 3 on'}
    >
      <p className="text-sm text-[var(--ink-soft)]">
        The strategy engine on its own. Its intraday trades are practice money; its long-term proposals wait for
        you in <Link to="/ai/decisions" className="underline">Decisions</Link>, or for the autopilot below.
      </p>
      {switchRow(
        'auto_paper_intraday',
        'Paper-trade intraday every session (experimental)',
        'Experimental: the intraday strategies lose money after charges in every backtest so far, so this is for watching them, not for results. Starts an intraday paper run at 9:15 AM IST each weekday and stops it at 3:30 PM, with positions squared off at 3:15 PM. It restarts itself after an interruption; stop it on Practice › Engine and it stays off for the rest of that day.'
      )}
      {switchRow(
        'scan_enabled',
        'Daily long-term scan',
        `Runs after the close at 4:00 PM IST over your ${prefs.universe.length} scrip and files long-term proposals for your decision.`
      )}
      {switchRow(
        'auto_paper_longterm',
        'Keep the long-term paper book running',
        'Runs the factor portfolio on paper with its own ₹3 lakh book: the top Nifty 200 stocks by momentum and low volatility, rebalanced at 9:20 AM on the first trading day of each month, in a liquid ETF whenever the Nifty is below its 200-day average. Also sells an approved long-term paper position at its stop or target (checked every 15 minutes in session) and sends a Telegram digest.'
      )}
      <p className="pt-3 doc-meta normal-case">
        Trading limits and which strategies may trade real money:{' '}
        <Link to="/practice/setup" className="underline">Practice › Setup</Link>.
      </p>
    </Sheet>
  );
};

export default EngineSwitches;
