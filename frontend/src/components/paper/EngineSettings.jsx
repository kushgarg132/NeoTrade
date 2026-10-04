import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Ruling } from '../doc/Doc';
import { Row, NumberField } from '../settings/Fields';
import api, { endpoints } from '../../utils/api';
import { useAuth } from '../../context/AuthContext';
import { formatCurrency } from '../../utils/formatters';
import { cn } from '../../utils/cn';
import { promotionGaps } from '../../utils/promotion';

/**
 * The engine's standing instructions: how large it may trade, what the daily
 * scan covers, and which strategies stay on paper. The daily loss limit is
 * not edited here -- it guards the real broker account too, so it belongs to
 * Guardrails in Settings; this sheet only states it.
 */

const SWITCH =
  'px-3 py-1 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors';

const SIZING = ['account_size', 'max_exposure', 'per_trade_cap'];

const EngineSettings = () => {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({ account_size: '', max_exposure: '', per_trade_cap: '' });
  const [saving, setSaving] = useState(false);
  const [strategyNames, setStrategyNames] = useState([]);
  const [promotion, setPromotion] = useState({});
  const [backtesting, setBacktesting] = useState({});
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
    api
      .get(endpoints.settings.preferences)
      .then((res) => {
        setPrefs(res.data);
        setDraft(Object.fromEntries(SIZING.map((key) => [key, res.data[key]])));
      })
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
    setSaving(true);
    try {
      const res = await api.put(endpoints.settings.preferences, patch);
      setPrefs(res.data);
    } finally {
      setSaving(false);
    }
  };

  if (!prefs) {
    return (
      <Sheet title="Engine mandate">
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

  const sizingRow = (key, label, hint) => (
    <Row label={label} hint={hint}>
      <NumberField
        value={draft[key]}
        onChange={(value) => setDraft((d) => ({ ...d, [key]: value }))}
        onCommit={() => save({ [key]: Number(draft[key]) })}
      />
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
          'Experimental: the intraday strategies lose money after charges in every backtest so far, so this is for watching them, not for results. Starts an intraday paper run at 09:15 IST each weekday and stops it at 15:30, with positions squared off at 15:15. It restarts itself after an interruption; stop it on the Engine tab and it stays off for the rest of that day.'
        )}
        {switchRow(
          'auto_paper_longterm',
          'Run the long-term engine every session',
          'Runs the factor portfolio on paper with its own ₹3 lakh book: the top Nifty 200 stocks by momentum and low volatility, rebalanced at 09:20 on the first trading day of each month, in a liquid ETF whenever the Nifty is below its 200-day average. Also sells an approved long-term position at its stop or target (checked every 15 minutes in session) and sends a Telegram digest. Proposals from the 16:00 scan wait for your approval.'
        )}
        <p className="pt-3 doc-meta normal-case">
          Paper only: a strategy you switched live trades real money only once it has passed its
          backtest and earned it on paper (see Strategies below).
        </p>
      </Sheet>

      <Sheet title="Engine mandate" meta={saving ? 'Saving…' : undefined}>
        {sizingRow('account_size', 'Account size', 'What position sizing risks a percentage of.')}
        {sizingRow('max_exposure', 'Maximum exposure', 'The engine will not open past this notional.')}
        {sizingRow('per_trade_cap', 'Per-trade cap', 'Hard notional ceiling for any single trade.')}

        <Row
          label="Daily loss limit"
          hint="Kill-switch trigger: reaching it halts new intraday orders for the rest of the day."
        >
          <span className="flex flex-col items-end gap-1">
            <span className="figure-md text-sm">{formatCurrency(prefs.daily_loss_limit)}</span>
            <Link to="/settings" className="doc-meta normal-case text-[var(--stamp)] hover:underline">
              Set in Guardrails
            </Link>
          </span>
        </Row>

        <p className="pt-3 doc-meta normal-case">
          Sizing risks up to 1% of {formatCurrency(prefs.account_size)} per trade at full
          conviction, scaled down as conviction falls.
        </p>
      </Sheet>

      <Sheet title="Daily scan">
        <Row
          label="Daily scan"
          hint="Runs after the close at 16:00 IST and files proposals for your decision."
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
          <p className="doc-meta normal-case pb-3 border-b border-[var(--rule)]">
            Every strategy trades paper unless you switch it live. Switching live sends real
            orders only once the strategy has passed its backtest and earned it here on paper:
            20 trading days, 30 trades, net profit after charges, profit factor 1.3, and no fall
            deeper than 5% of your account. Until then it keeps trading paper.
          </p>
          {strategyNames.map((name) => {
            const isLive = (prefs.live_strategies || []).includes(name);
            const earned = promotion[name]?.eligible;
            let hint = isLive ? 'Trading with real orders.' : 'Paper only.';
            if (promotion[name] && !earned) {
              const gaps = promotionGaps(promotion[name]);
              hint = `${isLive ? 'Switched live, still on paper. ' : ''}Needs ${gaps}.`;
            }
            return (
              <Row
                key={name}
                label={name}
                hint={
                  <>
                    {hint}
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
              </Row>
            );
          })}
        </Sheet>
      )}
    </div>
  );
};

export default EngineSettings;
