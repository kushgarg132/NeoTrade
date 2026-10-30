import React, { useEffect, useState } from 'react';
import { Sheet, Ruling } from '../settings/Panel';
import api, { endpoints, getPreferences } from '../../utils/api';
import { useAuth } from '../../context/AuthContext';
import { cn } from '../../utils/cn';
import { promotionGaps, shortStatus } from '../../utils/promotion';
import StrategyRow, { GO_LIVE_RULE, StrategyFold } from './StrategyRow';

/**
 * The engine's standing instructions: how large it may trade and which
 * strategies stay on paper. Its on/off switches (daily runs, the 4 PM scan)
 * are on Lab › Autopilot limits (components/settings/EngineSwitches.jsx). The daily loss limit is
 * not edited here -- it guards the real broker account too, so it belongs to
 * Guardrails in Settings; this sheet only states it.
 */

const SWITCH = 'min-h-11 px-3 rounded-full border text-[14px] font-semibold transition-colors';

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
      <Sheet title="Strategies">
        <Ruling rows={3} />
      </Sheet>
    );
  }

  return (
    <div className="space-y-4">
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
            <p className="doc-meta normal-case py-2 border-y border-[var(--border)]">
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
                          className="underline text-[var(--accent)]"
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
                      ? 'bg-[var(--loss)] text-[var(--surface)] border-[var(--loss)]'
                      : 'text-[var(--text-muted)] border-[var(--border)] bg-[var(--surface)]'
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
