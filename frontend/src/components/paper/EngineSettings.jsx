import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Ruling } from '../doc/Doc';
import { Row, NumberField } from '../settings/Fields';
import api, { endpoints } from '../../utils/api';
import { formatCurrency } from '../../utils/formatters';
import { cn } from '../../utils/cn';

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
            Every strategy trades paper unless you switch it live. A live strategy sends real
            orders to your broker; they leave this paper book and print on the statement.
          </p>
          {strategyNames.map((name) => {
            const isLive = (prefs.live_strategies || []).includes(name);
            return (
              <Row key={name} label={name} hint={isLive ? 'Trading with real orders.' : 'Paper only.'}>
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
