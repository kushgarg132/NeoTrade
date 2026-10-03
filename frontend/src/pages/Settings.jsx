import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Search, Loader2, Check, ExternalLink, Unplug, ArrowRight } from 'lucide-react';
import Layout from '../components/Layout';
import { Sheet, Empty, Ruling, Stamp, Tabs } from '../components/doc/Doc';
import { useTab } from '../hooks/useTab';
import { SECTIONS } from '../components/layout/sections';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { useAuth } from '../context/AuthContext';
import { Row, NumberField } from '../components/settings/Fields';
import { formatQuantity, formatDateTime } from '../utils/formatters';

/**
 * Standing instructions for the real account: who the broker is, the limits
 * the user holds themselves to, and which model writes the theses. The
 * engine's own settings (sizing, the daily scan, paper/live per strategy)
 * live in the Paper tab with everything else the engine does.
 */

/* -------------------------------------------------------------------------- */
/* Broker                                                                     */
/* -------------------------------------------------------------------------- */

const BROKER_TONE = {
  ACTIVE: 'success',
  NEEDS_LOGIN: 'warning',
  DEGRADED: 'destructive',
  UNCONFIGURED: 'secondary',
};

const BROKER_LABEL = { kite: 'Zerodha Kite', upstox: 'Upstox', angel_one: 'Angel One' };

const TextField = ({ id, label, ...props }) => (
  <div>
    <label htmlFor={id} className="field-label block mb-1">
      {label}
    </label>
    <input
      id={id}
      autoComplete="off"
      className="w-full bg-transparent border-b border-[var(--rule-strong)] py-1.5 text-sm focus:outline-none focus:border-[var(--stamp)]"
      {...props}
    />
  </div>
);

const BrokerSheet = () => {
  // A broker's redirect lands here: Upstox appends ?code=, Kite ?request_token=.
  const [searchParams, setSearchParams] = useSearchParams();
  const [pending, setPending] = useState(() => {
    const code = searchParams.get('code');
    if (code) return { broker: 'upstox', token: code };
    const requestToken = searchParams.get('request_token');
    if (requestToken) return { broker: 'kite', token: requestToken };
    return null;
  });
  const [broker, setBroker] = useState(pending?.broker || 'kite');
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  // Credential-save form (shown when UNCONFIGURED).
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [redirectUri, setRedirectUri] = useState('');

  // Redirect-flow connect (Kite / Upstox): paste the code/request_token.
  const [requestToken, setRequestToken] = useState('');

  // Credential-flow connect (Angel One): submitted fresh every time.
  const [clientCode, setClientCode] = useState('');
  const [password, setPassword] = useState('');
  const [totp, setTotp] = useState('');

  const refresh = (forBroker) =>
    api
      .get(endpoints.broker.status(forBroker))
      .then((res) => setState(res.data))
      .catch(() => setState({ state: 'UNCONFIGURED', connected: false, action: null }));

  useEffect(() => {
    setState(null);
    setNote(null);
    refresh(broker);
  }, [broker]);

  const needsSecret = broker !== 'angel_one';
  const needsRedirectUri = broker === 'upstox';

  const saveCredentials = async () => {
    if (!apiKey.trim() || (needsSecret && !apiSecret.trim())) return;
    setBusy(true);
    setNote(null);
    try {
      await api.post(endpoints.settings.brokerCredentials, {
        broker,
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim() || undefined,
        extra: needsRedirectUri ? redirectUri.trim() || undefined : undefined,
      });
      setApiKey('');
      setApiSecret('');
      setRedirectUri('');
      await refresh(broker);
    } catch (err) {
      setNote(err?.response?.data?.detail || 'Could not save the credentials');
    } finally {
      setBusy(false);
    }
  };

  const openLogin = async () => {
    setBusy(true);
    setNote(null);
    try {
      const res = await api.get(endpoints.broker.loginUrl(broker));
      window.open(res.data.url, '_blank', 'noopener');
      setNote(`Complete the ${BROKER_LABEL[broker]} login, then paste the code from the redirect URL if it isn't picked up automatically.`);
    } catch (err) {
      setNote(err?.response?.data?.detail || 'Could not build the login URL');
    } finally {
      setBusy(false);
    }
  };

  const connectWithRequestToken = async (token = requestToken) => {
    if (!token.trim()) return;
    setBusy(true);
    setNote(null);
    try {
      await api.post(endpoints.broker.connect(broker), { request_token: token.trim() });
      setRequestToken('');
      await refresh(broker);
    } catch (err) {
      setNote(err?.response?.data?.detail || `${BROKER_LABEL[broker]} rejected that code`);
    } finally {
      setBusy(false);
    }
  };

  // Submit a redirect's code once the sheet knows the broker is waiting for
  // one, then drop it from the URL so a reload doesn't replay a spent code.
  useEffect(() => {
    if (!pending || !state || pending.broker !== broker) return;
    setPending(null);
    setSearchParams({}, { replace: true });
    if (state.state === 'NEEDS_LOGIN') connectWithRequestToken(pending.token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, state, broker]);

  const connectWithCredentials = async () => {
    if (!clientCode.trim() || !password.trim() || !totp.trim()) return;
    setBusy(true);
    setNote(null);
    try {
      await api.post(endpoints.broker.connect(broker), {
        client_code: clientCode.trim(), password, totp: totp.trim(),
      });
      setClientCode('');
      setPassword('');
      setTotp('');
      await refresh(broker);
    } catch (err) {
      setNote(err?.response?.data?.detail || `${BROKER_LABEL[broker]} rejected that login`);
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await api.post(endpoints.broker.disconnect(broker));
      await refresh(broker);
    } finally {
      setBusy(false);
    }
  };

  const brokerPicker = (
    <div className="flex gap-1">
      {Object.keys(BROKER_LABEL).map((key) => (
        <button
          key={key}
          type="button"
          onClick={() => setBroker(key)}
          className={cn(
            'field-label px-2 py-1 border',
            key === broker
              ? 'border-[var(--stamp)] text-[var(--stamp)]'
              : 'border-transparent text-[var(--ink-faint)] hover:text-[var(--ink-soft)]',
          )}
        >
          {BROKER_LABEL[key]}
        </button>
      ))}
    </div>
  );

  if (!state) {
    return (
      <Sheet title="Broker" actions={brokerPicker}>
        <Ruling rows={2} />
      </Sheet>
    );
  }

  return (
    <Sheet
      title="Broker"
      actions={
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {brokerPicker}
          <Badge variant={BROKER_TONE[state.state]}>{state.state.replace('_', ' ')}</Badge>
        </div>
      }
    >
      <p className="text-sm text-[var(--ink-soft)]">
        A connected {BROKER_LABEL[broker]} session imports your trades into the journal and lets
        guardrails check your account.{' '}
        {broker === 'angel_one'
          ? 'Intraday runs still use delayed quotes — live ticks from Angel One aren’t supported yet.'
          : 'It also supplies live tick data for intraday runs.'}{' '}
        Real orders go out only for a strategy you’ve set to live, or a guardrail square-off you’ve
        set to Live; everything else stays on paper.
      </p>

      {state.state === 'UNCONFIGURED' ? (
        <div className="mt-4 space-y-3">
          <p className="doc-meta normal-case">
            {needsSecret
              ? `Paste the API key and secret from your ${BROKER_LABEL[broker]} app to configure this server.`
              : `Paste the API key from your ${BROKER_LABEL[broker]} app. Your account password and TOTP are entered fresh each time you connect — never stored.`}
          </p>
          <TextField id="broker-api-key" label="API key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          {needsSecret && (
            <TextField
              id="broker-api-secret" label="API secret" type="password"
              value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
            />
          )}
          {needsRedirectUri && (
            <TextField
              id="broker-redirect-uri" label="Redirect URI (registered with Upstox)"
              value={redirectUri} onChange={(e) => setRedirectUri(e.target.value)}
              placeholder="https://your-app.example.com/callback"
            />
          )}
          <Button
            variant="primary" size="sm" onClick={saveCredentials}
            disabled={busy || !apiKey.trim() || (needsSecret && !apiSecret.trim())}
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Save
          </Button>
        </div>
      ) : state.connected ? (
        <div className="mt-4 flex items-center justify-between gap-4">
          <Stamp label="Connected" tone="gain" />
          <Button variant="secondary" size="sm" onClick={disconnect} disabled={busy}>
            <Unplug className="w-3.5 h-3.5" />
            Disconnect
          </Button>
        </div>
      ) : broker === 'angel_one' ? (
        <div className="mt-4 space-y-3">
          <TextField id="angel-client-code" label="Client code" value={clientCode} onChange={(e) => setClientCode(e.target.value)} />
          <TextField id="angel-password" label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <TextField
            id="angel-totp" label="TOTP (from your authenticator app)" inputMode="numeric"
            value={totp} onChange={(e) => setTotp(e.target.value)}
          />
          <Button
            variant="primary" size="sm" onClick={connectWithCredentials}
            disabled={busy || !clientCode.trim() || !password.trim() || !totp.trim()}
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Connect
          </Button>
          <p className="doc-meta normal-case">Sessions end at midnight IST.</p>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <Button variant="primary" size="sm" onClick={openLogin} disabled={busy}>
            <ExternalLink className="w-3.5 h-3.5" />
            Connect {BROKER_LABEL[broker]}
          </Button>

          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor="request-token" className="field-label block mb-1">
                {broker === 'upstox' ? 'Code' : 'Request token'}
              </label>
              <input
                id="request-token"
                value={requestToken}
                onChange={(event) => setRequestToken(event.target.value)}
                placeholder="From the redirect URL after login"
                className="w-full bg-transparent border-b border-[var(--rule-strong)] py-1.5 text-sm focus:outline-none focus:border-[var(--stamp)]"
              />
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => connectWithRequestToken()}
              disabled={busy || !requestToken.trim()}
            >
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              Submit
            </Button>
          </div>

          <p className="doc-meta normal-case">
            {broker === 'kite'
              ? 'The token is single-use and expires in minutes. Sessions end daily at 06:00 IST.'
              : 'The code is single-use and expires in minutes. Sessions end daily at 03:30 IST.'}
          </p>
        </div>
      )}

      {note && <p className="mt-3 text-sm text-[var(--ink-soft)]">{note}</p>}
    </Sheet>
  );
};

/* -------------------------------------------------------------------------- */
/* Model                                                                      */
/* -------------------------------------------------------------------------- */

const ModelSheet = () => {
  const [models, setModels] = useState([]);
  const [current, setCurrent] = useState('');
  const [selected, setSelected] = useState('');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState(null);

  // A result belongs to the model it ran on; picking another clears it.
  useEffect(() => setTest(null), [selected]);

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const res = await api.post(endpoints.settings.omnirouteModelTest, { model: selected });
      setTest(res.data);
    } catch (err) {
      setTest({ ok: false, error: err?.response?.data?.detail || 'The test request failed' });
    } finally {
      setTesting(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get(endpoints.settings.omnirouteModels),
      api.get(endpoints.settings.omnirouteModel),
    ])
      .then(([modelsRes, currentRes]) => {
        if (cancelled) return;
        setModels(modelsRes.data);
        setCurrent(currentRes.data.model);
        setSelected(currentRes.data.model);
      })
      .catch(() => {
        if (!cancelled) setLoadError('Could not reach the OmniRoute gateway.');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    const list = term ? models.filter((m) => m.id.toLowerCase().includes(term)) : models;
    return list.slice(0, 40);
  }, [models, query]);

  const save = async () => {
    if (!selected.trim()) return;
    setSaving(true);
    setNote(null);
    try {
      await api.post(endpoints.settings.omnirouteModel, { model: selected });
      setCurrent(selected);
      setNote('Saved.');
    } catch (err) {
      setNote(
        err?.response?.status === 403
          ? 'The model applies to every account, so only an administrator can change it.'
          : 'Could not save the model.',
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet title="Analysis model" meta={`${models.length} available`}>
      {loadError ? (
        <Empty title="Gateway unreachable" detail={loadError} />
      ) : (
        <>
          <p className="text-sm text-[var(--ink-soft)]">
            Writes the thesis on each proposal and answers in chat. The trading engine itself
            never calls a model on the hot path.
          </p>

          <div className="mt-4">
            <label htmlFor="model-search" className="field-label block mb-1">
              In use
            </label>
            <div className="flex items-center gap-2 border-b border-[var(--rule-strong)] focus-within:border-[var(--stamp)]">
              <Search className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
              <input
                id="model-search"
                value={open ? query : selected}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setOpen(true);
                }}
                onFocus={() => {
                  setQuery('');
                  setOpen(true);
                }}
                placeholder="Filter models"
                className="w-full bg-transparent border-0 py-2 text-sm figure-md focus:outline-none"
              />
            </div>

            {open && (
              <ul className="sheet mt-px max-h-64 overflow-y-auto">
                {filtered.length === 0 ? (
                  <li className="px-3 py-2.5 text-sm text-[var(--ink-soft)]">No match.</li>
                ) : (
                  filtered.map((model) => (
                    <li key={model.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelected(model.id);
                          setOpen(false);
                        }}
                        className="w-full text-left px-3 py-2 text-sm figure-md border-b border-[var(--rule)] last:border-b-0 hover:bg-[var(--stamp-soft)]"
                      >
                        {model.id}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            )}
          </div>

          <div className="mt-4 flex items-center justify-between gap-3">
            <span className="doc-meta normal-case truncate">
              {selected === current ? `Current: ${current}` : `Changing from ${current}`}
            </span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="secondary" size="sm" onClick={runTest} disabled={testing || !selected}>
                {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                Test
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={save}
                disabled={saving || selected === current}
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                Save
              </Button>
            </div>
          </div>

          {testing && <p className="mt-2 doc-meta normal-case">Asking {selected} for a one-word reply…</p>}
          {test && (
            <p
              role="status"
              className={cn(
                'mt-2 text-sm px-3 py-2 border break-words',
                test.ok
                  ? 'text-[var(--gain)] border-[var(--gain)] bg-[var(--gain-wash)]'
                  : 'text-[var(--loss)] border-[var(--loss)] bg-[var(--loss-wash)]'
              )}
            >
              {test.ok
                ? `Works · ${(test.latency_ms / 1000).toFixed(1)}s · replied: ${test.reply}`
                : `Failed: ${test.error}`}
            </p>
          )}

          {note && <p className="mt-2 text-sm text-[var(--ink-soft)]">{note}</p>}
        </>
      )}
    </Sheet>
  );
};

/** The gateway key's own month, and how much each provider account has left. */
const Bar = ({ pct }) => (
  <div className="h-1.5 bg-[var(--paper-sunk)] flex-1 min-w-[3rem]" aria-hidden="true">
    <div
      className={cn('h-full', pct < 20 ? 'bg-[var(--loss)]' : 'bg-[var(--ink)]')}
      style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
    />
  </div>
);

const pctText = (pct) => (pct == null ? '—' : `${Math.round(pct)}% left`);

const ProviderRow = ({ provider }) => {
  const [open, setOpen] = useState(false);
  const known = provider.quotas.filter((q) => q.remaining_pct != null);
  const lowest = known.length ? Math.min(...known.map((q) => q.remaining_pct)) : null;
  return (
    <li className="border-b border-[var(--rule)] last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={!known.length}
        aria-expanded={open}
        className="w-full flex items-center gap-3 py-2 text-left disabled:cursor-default"
      >
        <span className="min-w-0 w-28 shrink-0">
          <span className="figure-md text-sm block truncate">{provider.provider}</span>
          <span className="doc-meta normal-case block truncate">{provider.plan || ' '}</span>
        </span>
        {known.length ? (
          <>
            <Bar pct={lowest} />
            <span className="figure-md text-xs w-20 text-right shrink-0">
              {known.length > 1 ? 'lowest ' : ''}{pctText(lowest)}
            </span>
          </>
        ) : (
          <span className="doc-meta normal-case">Quota not reported</span>
        )}
      </button>
      {open && (
        <ul className="pb-2 space-y-1.5">
          {known.map((quota) => (
            <li key={quota.name} className="flex items-center gap-3 text-xs">
              <span className="w-28 shrink-0 truncate text-[var(--ink-soft)]">{quota.name}</span>
              <Bar pct={quota.remaining_pct} />
              <span className="figure-md w-20 text-right shrink-0">{pctText(quota.remaining_pct)}</span>
            </li>
          ))}
          {known[0]?.reset_at && (
            <li className="doc-meta normal-case">Resets {formatDateTime(known[0].reset_at)}</li>
          )}
        </ul>
      )}
    </li>
  );
};

const UsageSheet = () => {
  const [usage, setUsage] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .get(endpoints.settings.omnirouteUsage)
      .then((res) => setUsage(res.data))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not read usage from the gateway.'));
  }, []);

  return (
    <Sheet title="Usage" meta={usage?.key_name ? `Key · ${usage.key_name}` : 'OmniRoute'} className="mt-3 sm:mt-4">
      {error ? (
        <Empty title="Usage unavailable" detail={error} />
      ) : !usage ? (
        <Ruling rows={3} />
      ) : (
        <>
          <p className="field-label mb-1">This month, this app's key</p>
          <p className="figure-md text-xl">{formatQuantity(usage.tokens.total)} tokens</p>
          <dl className="mt-2 grid grid-cols-3 gap-2">
            {[['Input', usage.tokens.input], ['Output', usage.tokens.output], ['Reasoning', usage.tokens.reasoning]].map(([label, value]) => (
              <div key={label}>
                <dt className="field-label">{label}</dt>
                <dd className="figure-md text-sm">{formatQuantity(value)}</dd>
              </div>
            ))}
          </dl>
          <p className="doc-meta normal-case mt-2">
            Cost ${Number(usage.cost.used_usd || 0).toFixed(2)}
            {usage.cost.limit_usd != null ? ` of $${Number(usage.cost.limit_usd).toFixed(2)}` : ' · no cost limit'}
            {usage.cost.reset_at ? ` · resets ${formatDateTime(usage.cost.reset_at)}` : ''}
          </p>

          <p className="field-label mt-4 mb-1">Providers · quota left</p>
          <p className="doc-meta normal-case mb-1">
            The gateway's shared accounts, not only this app's use. Tap one for each model.
          </p>
          <ul>
            {usage.providers.map((provider) => (
              <ProviderRow key={provider.provider} provider={provider} />
            ))}
          </ul>
        </>
      )}
    </Sheet>
  );
};

/* -------------------------------------------------------------------------- */
/* Guardrails                                                                 */
/* -------------------------------------------------------------------------- */

const GUARD_FIELDS = [
  'max_trades_per_day', 'cooldown_after_losses', 'cooldown_minutes', 'daily_loss_limit',
  'max_option_trades_per_day', 'max_option_lots',
];

const GuardrailsSheet = () => {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({});
  const [telegram, setTelegram] = useState(null);
  const [linkUrl, setLinkUrl] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get(endpoints.settings.preferences)
      .then((res) => {
        setPrefs(res.data);
        setDraft(Object.fromEntries(GUARD_FIELDS.map((key) => [key, res.data[key]])));
      })
      .catch(() => setPrefs(null));
    api
      .get(endpoints.guardrails.status)
      .then((res) => setTelegram(res.data.telegram))
      .catch(() => setTelegram(null));
  }, []);

  const save = (patch) => api.put(endpoints.settings.preferences, patch).then((res) => setPrefs(res.data));

  const act = (request, onDone) => {
    setBusy(true);
    setNote(null);
    request()
      .then(onDone)
      .catch((err) => setNote(err?.response?.data?.detail || 'That did not work'))
      .finally(() => setBusy(false));
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
        onCommit={() => save({ [key]: Math.max(0, Math.round(Number(draft[key]) || 0)) })}
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
      <p className="doc-meta normal-case pb-3 border-b border-[var(--rule)]">
        Limits you set for yourself. NeoTrade checks them against your broker every minute during the
        session and alerts you when one is crossed. It cannot stop an order you place in your broker's
        own app.
      </p>

      <Row label="Watch my broker" hint="Checks every connected broker from 09:15 to 15:35 IST.">
        <button
          type="button"
          role="switch"
          aria-checked={prefs.guardrails_enabled}
          onClick={() => save({ guardrails_enabled: !prefs.guardrails_enabled })}
          className={cn(
            'px-3 py-1 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors',
            prefs.guardrails_enabled
              ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
              : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
          )}
        >
          {prefs.guardrails_enabled ? 'On' : 'Off'}
        </button>
      </Row>

      <Row
        label="Daily loss limit"
        hint="Checked against your broker's own day P&L. Reaching it also trips the engine's kill-switch for the day."
      >
        <NumberField
          value={draft.daily_loss_limit}
          onChange={(value) => setDraft((d) => ({ ...d, daily_loss_limit: value }))}
          onCommit={() => save({ daily_loss_limit: Number(draft.daily_loss_limit) })}
        />
      </Row>

      {numberRow('max_trades_per_day', 'Trades per day', 'Alert when you open more than this. 0 is off.')}
      {numberRow('cooldown_after_losses', 'Cooldown after losses in a row', 'Start a cooldown after this many losses in a row. 0 is off.')}
      {numberRow('cooldown_minutes', 'Cooldown length, minutes', 'Any trade opened inside it is flagged.')}
      {numberRow('max_option_trades_per_day', 'Options trades per day', 'Alert when you open more options trades than this. 0 is off.')}
      {numberRow('max_option_lots', 'Lots per options trade', 'Alert when one options position is bigger than this many lots. Needs Kite connected for lot sizes. 0 is off.')}

      <Row
        label="Warn on unhedged option selling"
        hint="Alert when you sell an option with no bought option on the same underlying open to cap the loss. A sold option's loss has no fixed limit."
      >
        <button
          type="button"
          role="switch"
          aria-checked={Boolean(prefs.warn_naked_options)}
          onClick={() => save({ warn_naked_options: !prefs.warn_naked_options })}
          className={cn(
            'px-3 py-1 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors',
            prefs.warn_naked_options
              ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
              : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
          )}
        >
          {prefs.warn_naked_options ? 'On' : 'Off'}
        </button>
      </Row>

      <Row
        label="Square off at the loss limit"
        hint={
          prefs.auto_square_off === 'live'
            ? 'Live: when the daily loss limit is hit, NeoTrade places market orders to close your NSE intraday (MIS) positions, once a day. Delivery and F&O positions are never touched.'
            : 'Preview alerts you with the exact exit orders it would place, without sending them. Live sends them. Only NSE intraday (MIS) positions, once a day.'
        }
      >
        <div className="flex" role="radiogroup" aria-label="Square off at the loss limit">
          {[
            ['off', 'Off'],
            ['preview', 'Preview'],
            ['live', 'Live'],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={prefs.auto_square_off === value}
              onClick={() => {
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
              className={cn(
                'px-3 py-1 border -ml-px first:ml-0 font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors',
                prefs.auto_square_off === value
                  ? value === 'live'
                    ? 'bg-[var(--loss)] text-[var(--paper)] border-[var(--loss)]'
                    : 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
                  : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </Row>

      <Row
        label="Telegram alerts"
        hint={
          telegram?.configured === false
            ? 'Not set up on this server yet. Alerts still appear in the app.'
            : 'Alerts arrive on your phone even when the app is closed.'
        }
      >
        {telegram?.configured &&
          (telegram.linked ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() =>
                act(() => api.delete(endpoints.guardrails.telegram), () =>
                  setTelegram((t) => ({ ...t, linked: false }))
                )
              }
            >
              Unlink
            </Button>
          ) : linkUrl ? (
            <div className="flex gap-2">
              <a href={linkUrl} target="_blank" rel="noreferrer">
                <Button variant="secondary" size="sm">
                  <ExternalLink className="w-3.5 h-3.5" />
                  Open Telegram
                </Button>
              </a>
              <Button
                variant="primary"
                size="sm"
                disabled={busy}
                onClick={() =>
                  act(() => api.post(endpoints.guardrails.verify), () => {
                    setLinkUrl(null);
                    setTelegram((t) => ({ ...t, linked: true }));
                  })
                }
              >
                I tapped Start
              </Button>
            </div>
          ) : (
            <Button
              variant="primary"
              size="sm"
              disabled={busy}
              onClick={() => act(() => api.post(endpoints.guardrails.link), (res) => setLinkUrl(res.data.url))}
            >
              Link Telegram
            </Button>
          ))}
      </Row>
      {note && <p className="doc-meta normal-case pt-2">{note}</p>}
    </Sheet>
  );
};

/* -------------------------------------------------------------------------- */
/* Portfolio review                                                           */
/* -------------------------------------------------------------------------- */

const PortfolioSheet = ({ isAdmin }) => {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({});
  const [audience, setAudience] = useState(null);

  useEffect(() => {
    api
      .get(endpoints.settings.preferences)
      .then((res) => {
        setPrefs(res.data);
        setDraft({
          portfolio_max_loss_pct: res.data.portfolio_max_loss_pct,
          portfolio_max_weight_pct: res.data.portfolio_max_weight_pct,
        });
      })
      .catch(() => setPrefs(null));
    if (isAdmin) {
      api
        .get(endpoints.settings.portfolioVerdicts)
        .then((res) => setAudience(res.data.audience))
        .catch(() => setAudience(null));
    }
  }, [isAdmin]);

  if (!prefs) return null;

  const commit = (key) => {
    const value = Math.min(100, Math.max(1, Number(draft[key]) || prefs[key]));
    api.put(endpoints.settings.preferences, { [key]: value }).then((res) => setPrefs(res.data));
  };

  const setVerdicts = (next) => {
    if (
      next === 'all' &&
      !window.confirm(
        'Show SELL / HOLD / ADD to every user? Giving stock verdicts to users needs SEBI Research Analyst registration.'
      )
    ) {
      return;
    }
    api.put(endpoints.settings.portfolioVerdicts, { audience: next }).then((res) => setAudience(res.data.audience));
  };

  return (
    <Sheet title="Portfolio review">
      <p className="doc-meta normal-case pb-3 border-b border-[var(--rule)]">
        Your own limits for the Portfolio page's review: a holding past either one counts against it.
      </p>
      {[
        ['portfolio_max_loss_pct', 'Loss limit, % below cost', 'A holding this far under its average cost.'],
        ['portfolio_max_weight_pct', 'Size limit, % of portfolio', 'A holding larger than this share of the whole.'],
      ].map(([key, label, hint]) => (
        <Row key={key} label={label} hint={hint}>
          <NumberField
            value={draft[key] ?? ''}
            onChange={(value) => setDraft((d) => ({ ...d, [key]: value }))}
            onCommit={() => commit(key)}
          />
        </Row>
      ))}
      {isAdmin && audience && (
        <Row
          label="Who sees verdicts"
          hint="Deployment-wide. Everyone else sees the facts with serious holdings marked Review first. Verdicts for all users need SEBI RA registration."
        >
          <button
            type="button"
            role="switch"
            aria-checked={audience === 'all'}
            onClick={() => setVerdicts(audience === 'all' ? 'admin' : 'all')}
            className={cn(
              'px-3 py-1 border font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors',
              audience === 'all'
                ? 'bg-[var(--loss)] text-[var(--paper)] border-[var(--loss)]'
                : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
            )}
          >
            {audience === 'all' ? 'All users' : 'Admins only'}
          </button>
        </Row>
      )}
    </Sheet>
  );
};

const BETA_ROWS = [
  ['users', 'Signed up'],
  ['users_with_trades', 'With trades in the journal'],
  ['weekly_active', 'Opened the journal in the last 7 days'],
  ['returned_from_last_week', 'Came back from the week before'],
  ['guardrails_on', 'Guardrails on'],
  ['telegram_linked', 'Telegram linked'],
];

/** Admin only: Phase 12's question — do beta users come back? */
const BetaSheet = () => {
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    api
      .get(endpoints.journal.betaMetrics)
      .then((res) => setMetrics(res.data))
      .catch(() => setMetrics(null));
  }, []);

  if (!metrics) return null;

  return (
    <Sheet title="Beta" meta="All users">
      {BETA_ROWS.map(([key, label]) => (
        <Row key={key} label={label}>
          <span className="figure-md text-sm">
            {metrics[key]}
            {key === 'returned_from_last_week' && ` of ${metrics.active_last_week}`}
          </span>
        </Row>
      ))}
      <Row label="Losing days followed by a journal visit" hint="Within 3 days of the loss.">
        <span className="figure-md text-sm">
          {metrics.losing_days_followed_by_open} of {metrics.losing_days}
        </span>
      </Row>
    </Sheet>
  );
};

/** Sections the phone's bottom bar has no room for; "More" lands here. */
const MoreSections = () => (
  <nav aria-label="More sections" className="sheet lg:hidden">
    <ul className="grid grid-cols-2">
      {SECTIONS.filter((item) => !item.primary).map((item, index) => (
        <li
          key={item.path}
          className={cn(index % 2 === 0 && 'border-r border-[var(--rule)]', index > 1 && 'border-t border-[var(--rule)]')}
        >
          <Link
            to={item.path}
            className="flex items-center gap-2 px-3 min-h-11 field-label text-[var(--ink)] hover:bg-[var(--paper-sunk)]"
          >
            <item.icon className="w-4 h-4 text-[var(--ink-soft)]" strokeWidth={1.75} />
            {item.label}
          </Link>
        </li>
      ))}
    </ul>
  </nav>
);

const Settings = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const tabs = [
    { id: 'broker', label: 'Broker' },
    { id: 'guardrails', label: 'Limits' },
    { id: 'portfolio', label: 'Review' },
    { id: 'ai', label: 'AI' },
    ...(isAdmin ? [{ id: 'beta', label: 'Beta' }] : []),
  ];
  const [tab, setTab] = useTab(tabs.map((t) => t.id));
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <MoreSections />
        <Link
          to="/paper/settings"
          className="flex items-center justify-between gap-3 sheet px-3 py-2.5 sm:px-4 border-dashed border-[var(--stamp)] hover:bg-[var(--stamp-soft)] transition-colors"
        >
          <span className="min-w-0 text-sm text-[var(--ink-soft)]">
            <span className="field-label text-[var(--stamp)]">Engine settings</span> are in Paper trading
          </span>
          <ArrowRight className="w-4 h-4 shrink-0 text-[var(--stamp)]" />
        </Link>
        <div>
          <Tabs tabs={tabs} active={tab} onSelect={setTab} label="Settings sections" />
          <div className="pt-3 sm:pt-4">
            {tab === 'broker' && <BrokerSheet />}
            {tab === 'guardrails' && <GuardrailsSheet />}
            {tab === 'portfolio' && <PortfolioSheet isAdmin={isAdmin} />}
            {tab === 'ai' && (
              <>
                <ModelSheet />
                {isAdmin && <UsageSheet />}
              </>
            )}
            {tab === 'beta' && isAdmin && <BetaSheet />}
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default Settings;
