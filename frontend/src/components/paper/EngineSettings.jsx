import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Ruling } from '../doc/Doc';
import { Row, NumberField } from '../settings/Fields';
import api, { endpoints, getPreferences } from '../../utils/api';
import { useAuth } from '../../context/AuthContext';
import { formatCurrency } from '../../utils/formatters';
import { cn } from '../../utils/cn';
import { promotionGaps, shortStatus } from '../../utils/promotion';
import StrategyRow, { GO_LIVE_RULE, StrategyFold } from './StrategyRow';

/**
 * The engine's standing instructions: how large it may trade, what the daily
 * scan covers, and which strategies stay on paper. The daily loss limit is
 * not edited here -- it guards the real broker account too, so it belongs to
 * Guardrails in Settings; this sheet only states it.
 */

const SWITCH =
  'px-3 py-1 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors';

const EngineSettings = () => {
  const [prefs, setPrefs] = useState(null);
  const [strategyNames, setStrategyNames] = useState([]);
  const [promotion, setPromotion] = useState({});
  const [backtesting, setBacktesting] = useState({});
  const [openStrategy, setOpenStrategy] = useState(null);
  const [strategiesOpen, setStrategiesOpen] = useState(false);
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const runBacktest = async (name) => {
    setBacktesting((state) => ({ ...state, [name]: 'Starting…' }));
    try {
      const res = await api.post(endpoints.trading.backtest(name));
      setBacktesting((state) => ({
        ...state,
        [name]: `Running on ${res.data.history} history. Reopen this page in a few minutes.`,
      }));
    } catch (err) {
      setBacktesting((state) => ({ ...state, [name]: err?.response?.data?.detail || 'Could not start' }));
    }
  };

  useEffect(() => {
    getPreferences()
      .then((res) => setPrefs(res.data))
      .catch(() => setPrefs(null));
    api
      .get(endpoints.settings.strategies)
      .then((res) => setStrategyNames(res.data))
      .catch(() => setStrategyNames([]));
    api
      .get(endpoints.settings.promotion)
      .then((res) => setPromotion(Object.fromEntries(res.data.map((row) => [row.name, row]))))
      .catch(() => setPromotion({}));
  }, []);

  const save = async (patch) => {
    const res = await api.put(endpoints.settings.preferences, patch);
    setPrefs(res.data);
  };

  if (!prefs) {
    return (
      <Sheet title="Daily auto-run">
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
    <div className="space-y-4">
      <Sheet
        title="Daily auto-run"
        meta={prefs.auto_paper_intraday || prefs.auto_paper_longterm ? 'On' : 'Off'}
      >
        {switchRow(
          'auto_paper_intraday',
          'Paper-trade intraday every session (experimental)',
          'Experimental: the intraday strategies lose money after charges in every backtest so far, so this is for watching them, not for results. Starts an intraday paper run at 9:15 AM IST each weekday and stops it at 3:30 PM, with positions squared off at 3:15 PM. It restarts itself after an interruption; stop it on the Engine tab and it stays off for the rest of that day.'
        )}
        {switchRow(
          'auto_paper_longterm',
          'Run the long-term engine every session',
          'Runs the factor portfolio on paper with its own ₹3 lakh book: the top Nifty 200 stocks by momentum and low volatility, rebalanced at 9:20 AM on the first trading day of each month, in a liquid ETF whenever the Nifty is below its 200-day average. Also sells an approved long-term position at its stop or target (checked every 15 minutes in session) and sends a Telegram digest. Proposals from the 4:00 PM scan wait for your approval, or for the autopilot if it is on.'
        )}
        <p className="pt-3 doc-meta normal-case">
          Practice money. Its long-term proposals wait for you in{' '}
          <Link to="/ai/decisions" className="underline">Decisions</Link>, or the{' '}
          <Link to="/ai/autopilot" className="underline">Autopilot</Link> acts on them — on paper it trades this
          same book, tagged autopilot.
          A strategy you switched live trades real money only once it has passed its backtest and
          earned it on paper (see Strategies below).
        </p>
      </Sheet>

      <Sheet title="Trading limits" meta="Paper and live">
        {[
          ['Account size', prefs.account_size],
          ['Max invested', prefs.max_exposure],
          ['Per trade', prefs.per_trade_cap],
          ['Daily loss limit', prefs.daily_loss_limit],
        ].map(([label, value]) => (
          <Row key={label} label={label}>
            <span className="figure-md text-sm">{formatCurrency(value)}</span>
          </Row>
        ))}
        <p className="pt-3 doc-meta normal-case">
          Sizing risks up to 1% of {formatCurrency(prefs.account_size)} per trade at full
          conviction, scaled down as conviction falls. One set for paper and live:{' '}
          <Link to="/ai/autopilot" className="underline">change them on AI › Autopilot</Link>.
        </p>
      </Sheet>

      <Sheet title="Daily scan">
        <Row
          label="Daily scan"
          hint="Runs after the close at 4:00 PM IST and files proposals for your decision."
        >
          <button
            type="button"
            role="switch"
            aria-checked={prefs.scan_enabled}
            onClick={() => save({ scan_enabled: !prefs.scan_enabled })}
            className={cn(
              SWITCH,
              prefs.scan_enabled
                ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
                : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
            )}
          >
            {prefs.scan_enabled ? 'On' : 'Off'}
          </button>
        </Row>

        <Row label="Scan universe" hint="Scrip the daily scan considers.">
          <span className="figure-md text-sm">{prefs.universe.length} scrip</span>
        </Row>
      </Sheet>

      {strategyNames.length > 0 && (
        <Sheet title="Strategies" meta={`${(prefs.live_strategies || []).length} live`}>
          <StrategyFold
            count={strategyNames.length}
            ready={strategyNames.filter((n) => promotion[n]?.eligible).length}
            live={(prefs.live_strategies || []).length}
            open={strategiesOpen}
            onToggle={() => setStrategiesOpen((value) => !value)}
          />
          {strategiesOpen && (
            <p className="doc-meta normal-case py-2 border-y border-[var(--rule)]">
              Every strategy trades paper unless you switch it live. {GO_LIVE_RULE} Until then it keeps trading paper.
            </p>
          )}
          {strategiesOpen && strategyNames.map((name) => {
            const isLive = (prefs.live_strategies || []).includes(name);
            const earned = promotion[name]?.eligible;
            let hint = isLive ? 'Trading with real orders.' : 'Paper only.';
            if (promotion[name] && !earned) {
              const gaps = promotionGaps(promotion[name]);
              hint = `${isLive ? 'Switched live, still on paper. ' : ''}Needs ${gaps}.`;
            }
            return (
              <StrategyRow
                key={name}
                name={name}
                status={isLive ? `live · ${shortStatus(promotion[name])}` : shortStatus(promotion[name])}
                open={openStrategy === name}
                onToggle={() => setOpenStrategy((current) => (current === name ? null : name))}
                detail={hint}
                extra={
                  <>
                    {isAdmin && (
                      <>
                        {' '}
                        <button
                          type="button"
                          className="underline text-[var(--stamp)]"
                          onClick={() => runBacktest(name)}
                          disabled={Boolean(backtesting[name])}
                        >
                          Run a year's backtest
                        </button>
                        {backtesting[name] && <span> {backtesting[name]}</span>}
                      </>
                    )}
                  </>
                }
              >
                <button
                  type="button"
                  role="switch"
                  aria-checked={isLive}
                  aria-label={`${name}: ${isLive ? 'live, real orders' : 'paper only'}`}
                  onClick={() => {
                    const next = isLive
                      ? (prefs.live_strategies || []).filter((n) => n !== name)
                      : [...(prefs.live_strategies || []), name];
                    save({ live_strategies: next });
                  }}
                  className={cn(
                    SWITCH,
                    isLive
                      ? 'bg-[var(--loss)] text-[var(--paper)] border-[var(--loss)]'
                      : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
                  )}
                >
                  {isLive ? 'Live' : 'Paper'}
                </button>
              </StrategyRow>
            );
          })}
        </Sheet>
      )}
    </div>
  );
};

export default EngineSettings;
