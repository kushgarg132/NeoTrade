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
 * The engine's standing instructions: how large it may trade and which
 * strategies stay on paper. Its on/off switches (daily runs, the 4 PM scan)
 * are on AI › Autopilot (components/settings/EngineSwitches.jsx). The daily loss limit is
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
      <Sheet title="Trading limits">
        <Ruling rows={3} />
      </Sheet>
    );
  }

  return (
    <div className="space-y-4">
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
          <Link to="/ai/autopilot" className="underline">change them on AI › Autopilot</Link>, where the
          engine's daily runs and scan are switched on and off too.
        </p>
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
