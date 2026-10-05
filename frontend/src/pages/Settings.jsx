import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Search, Loader2, Check, ExternalLink, Unplug, ArrowRight, ChevronDown } from 'lucide-react';
import Layout from '../components/Layout';
import { Sheet, Empty, Ruling, Stamp, Tabs } from '../components/doc/Doc';
import { useTab } from '../hooks/useTab';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { useAuth } from '../context/AuthContext';
import { Row, NumberField } from '../components/settings/Fields';
import { formatCurrency, formatQuantity, formatDateTime } from '../utils/formatters';
import { Avatar } from '../components/common/Avatar';
import { usePendingCount } from '../context/pendingContext';

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

const ROLE_OPTIONS = [
  ['ai', 'AI account', 'The autopilot trades it by itself, within its limits'],
  ['mine', 'My account', 'You trade; the AI only proposes cards you confirm'],
];

/** Which account is for what (backend/brokers/roles.py). Orders route by
    role and never fall back to the other account. */
const BrokerRole = ({ broker }) => {
  const [roles, setRoles] = useState(null);
  const [note, setNote] = useState(null);
  useEffect(() => {
    api.get(endpoints.settings.preferences).then((res) => setRoles(res.data.broker_roles || {})).catch(() => setRoles({}));
  }, []);
  if (!roles) return null;
  const choose = (role) => {
    const next = { ...roles };
    if (next[broker] === role) delete next[broker];
    else next[broker] = role;
    setNote(null);
    api.put(endpoints.settings.preferences, { broker_roles: next })
      .then((res) => setRoles(res.data.broker_roles || {}))
      .catch((err) => {
        const detail = err?.response?.data?.detail;
        setNote(Array.isArray(detail) ? detail[0]?.msg?.replace('Value error, ', '') : detail || 'Could not save.');
      });
  };
  return (
    <div className="mt-3 pt-3 border-t border-[var(--rule)]">
      <p className="field-label mb-1.5">This account is</p>
      <div role="radiogroup" aria-label="Account role" className="grid grid-cols-2 gap-2">
        {ROLE_OPTIONS.map(([role, label, hint]) => (
          <button
            key={role}
            type="button"
            role="radio"
            aria-checked={roles[broker] === role}
            onClick={() => choose(role)}
            className={cn(
              'text-left p-2.5 border transition-colors min-h-11',
              roles[broker] === role ? 'border-[var(--stamp)] bg-[var(--stamp-soft)]' : 'border-[var(--rule-strong)] hover:border-[var(--ink)]',
            )}
          >
            <span className="block text-sm font-semibold">{label}</span>
            <span className="block doc-meta normal-case mt-0.5">{hint}</span>
          </button>
        ))}
      </div>
      {note && <p className="doc-meta normal-case text-[var(--loss)] mt-1.5">{note}</p>}
    </div>
  );
};

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
      {state.state !== 'UNCONFIGURED' && <BrokerRole broker={broker} />}

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

const TIER_ROWS = [
  { id: 'deep', label: 'Deep', hint: 'Chat, portfolio review, news scoring, peers' },
  { id: 'standard', label: 'Standard', hint: 'Research reports and theses, index explanations' },
  { id: 'fast', label: 'Fast', hint: 'Event tagging, symbol lookup, article sentiment' },
];

const STEP_BUTTON =
  'w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left text-sm border-b border-[var(--rule)] last:border-b-0 hover:bg-[var(--stamp-soft)]';

/**
 * Family -> model line -> version, the way people think about models
 * ("Claude, then Opus, then 4.6"). A family with one line skips that step.
 * Search all keeps the raw list for an id the tree does not place well.
 */
const ModelChooser = ({ catalog, models, onPick, onClose }) => {
  const [familyKey, setFamilyKey] = useState(null);
  const [lineKey, setLineKey] = useState(null);
  const [search, setSearch] = useState(false);
  const [query, setQuery] = useState('');

  const family = catalog.find((f) => f.key === familyKey);
  const line = family && (family.lines.length === 1 ? family.lines[0] : family.lines.find((l) => l.key === lineKey));
  const step = search ? 'search' : !family ? 'family' : !line ? 'line' : 'version';

  const back = () => {
    if (search) setSearch(false);
    else if (line && family.lines.length > 1) setLineKey(null);
    else if (family) setFamilyKey(null);
    else onClose();
  };

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (term ? models.filter((m) => m.id.toLowerCase().includes(term)) : models).slice(0, 40);
  }, [models, query]);

  // Versions grouped under their number, newest first (the API already sorted them).
  const groups = useMemo(() => {
    if (!line) return [];
    const out = [];
    for (const model of line.models) {
      const key = model.version || model.label;
      const last = out[out.length - 1];
      if (last && last.key === key && model.version) last.models.push(model);
      else out.push({ key, models: [model] });
    }
    return out;
  }, [line]);

  const crumb = [family?.label, family && family.lines.length > 1 ? line?.label : null].filter(Boolean).join(' › ');

  return (
    <div className="mt-2 sheet">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[var(--rule-strong)] bg-[var(--paper-sunk)]">
        <button type="button" onClick={back} className="field-label text-[var(--stamp)] hover:underline min-h-8">
          ‹ {step === 'family' ? 'Close' : 'Back'}
        </button>
        <span className="doc-meta normal-case truncate">
          {step === 'search' ? 'All models' : crumb || 'Choose a family'}
        </span>
        {step !== 'search' ? (
          <button type="button" onClick={() => setSearch(true)} className="field-label text-[var(--ink-soft)] hover:underline min-h-8">
            Search all
          </button>
        ) : (
          <span />
        )}
      </div>
      <div className="max-h-72 overflow-y-auto">
        {step === 'family' &&
          catalog.map((f) => (
            <button key={f.key} type="button" className={STEP_BUTTON} onClick={() => { setFamilyKey(f.key); setLineKey(null); }}>
              <span className="figure-md">{f.label}</span>
              <span className="doc-meta normal-case">{f.count} ›</span>
            </button>
          ))}
        {step === 'line' &&
          family.lines.map((l) => (
            <button key={l.key} type="button" className={STEP_BUTTON} onClick={() => setLineKey(l.key)}>
              <span className="figure-md">{l.label}</span>
              <span className="doc-meta normal-case">{l.models.length} ›</span>
            </button>
          ))}
        {step === 'version' &&
          groups.map((group) => (
            <div key={group.key}>
              {group.models[0].version && (
                <p className="px-3 pt-2 pb-1 field-label text-[var(--ink)] bg-[var(--paper-sunk)]">
                  {line.key === 'all' || line.key === 'other' ? '' : `${line.label} `}{group.key}
                </p>
              )}
              {group.models.map((model) => (
                <button key={model.id} type="button" className={STEP_BUTTON} onClick={() => onPick(model.id)}>
                  <span className="min-w-0">
                    <span className="text-sm block truncate">
                      {model.version ? model.variant || 'standard' : model.label}
                    </span>
                    <span className="doc-meta normal-case block truncate">{model.id}</span>
                  </span>
                  <span className="doc-meta normal-case shrink-0">{model.provider}</span>
                </button>
              ))}
            </div>
          ))}
        {step === 'search' && (
          <>
            <div className="flex items-center gap-2 px-3 border-b border-[var(--rule-strong)]">
              <Search className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter every model id"
                className="w-full bg-transparent border-0 py-2 text-sm focus:outline-none"
                aria-label="Filter models"
              />
            </div>
            {filtered.length === 0 ? (
              <p className="px-3 py-2.5 text-sm text-[var(--ink-soft)]">No match.</p>
            ) : (
              filtered.map((model) => (
                <button key={model.id} type="button" className={STEP_BUTTON} onClick={() => onPick(model.id)}>
                  <span className="figure-md truncate">{model.id}</span>
                </button>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
};

/** One model choice: pick it step by step, test it, save it. */
const ModelRow = ({ label, hint, value, fallback, models, catalog, onSave, clearable, expanded, onToggle }) => {
  const [selected, setSelected] = useState(value || '');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(null);
  const [test, setTest] = useState(null);
  const [note, setNote] = useState(null);

  useEffect(() => setSelected(value || ''), [value]);
  // A result belongs to the model it ran on; picking another clears it.
  useEffect(() => setTest(null), [selected]);

  const effective = selected || fallback;

  const runTest = async () => {
    setBusy('test');
    try {
      const res = await api.post(endpoints.settings.omnirouteModelTest, { model: effective });
      setTest(res.data);
    } catch (err) {
      setTest({ ok: false, error: err?.response?.data?.detail || 'The test request failed' });
    } finally {
      setBusy(null);
    }
  };

  const save = async (model) => {
    setBusy('save');
    setNote(null);
    try {
      await onSave(model);
      setNote(model ? 'Saved.' : 'Cleared: uses the fallback.');
    } catch (err) {
      setNote(err?.response?.status === 403 ? 'Only an administrator can change models.' : 'Could not save.');
    } finally {
      setBusy(null);
    }
  };

  // Collapsed: one line -- the tier and the model it runs on. Tap to open.
  if (!expanded) {
    return (
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={false}
        className="w-full py-3 min-h-11 flex items-center gap-3 border-b border-[var(--rule)] last:border-b-0 text-left hover:bg-[var(--paper-sunk)] transition-colors"
      >
        <span className="field-label text-[var(--ink)] w-20 shrink-0">{label}</span>
        <span className={cn('flex-1 min-w-0 truncate text-sm', selected ? 'figure-md' : 'text-[var(--ink-faint)]')}>
          {selected || (clearable ? `Fallback: ${fallback}` : 'No model')}
        </span>
        <ChevronDown className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" aria-hidden="true" />
      </button>
    );
  }

  return (
    <div className="py-3 border-b border-[var(--rule)] last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <button type="button" onClick={onToggle} aria-expanded className="flex items-center gap-1.5 field-label text-[var(--ink)]">
          {label}
          <ChevronDown className="w-4 h-4 rotate-180 text-[var(--ink-faint)]" aria-hidden="true" />
        </button>
        {clearable && value && (
          <button type="button" onClick={() => save(null)} disabled={busy !== null} className="field-label text-[var(--stamp)] hover:underline">
            Use fallback
          </button>
        )}
      </div>
      <p className="doc-meta normal-case mt-0.5">{hint}</p>
      <div className="mt-2 flex items-center justify-between gap-3 border-b border-[var(--rule-strong)] pb-2">
        <span className={cn('min-w-0 truncate text-sm', selected ? 'figure-md' : 'text-[var(--ink-faint)]')}>
          {selected || (clearable ? `Uses fallback: ${fallback}` : 'No model')}
        </span>
        <button
          type="button"
          onClick={() => setOpen((value_) => !value_)}
          aria-expanded={open}
          className="field-label text-[var(--stamp)] hover:underline shrink-0 min-h-8"
        >
          {open ? 'Close' : 'Change'}
        </button>
      </div>
      {open && (
        <ModelChooser
          catalog={catalog}
          models={models}
          onClose={() => setOpen(false)}
          onPick={(id) => {
            setSelected(id);
            setOpen(false);
          }}
        />
      )}
      <div className="mt-2 flex items-center justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={runTest} disabled={busy !== null || !effective}>
          {busy === 'test' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
          Test
        </Button>
        <Button variant="primary" size="sm" onClick={() => save(selected)} disabled={busy !== null || !selected || selected === value}>
          {busy === 'save' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
          Save
        </Button>
      </div>
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
          {test.ok ? `${test.model} works · ${(test.latency_ms / 1000).toFixed(1)}s · replied: ${test.reply}` : `Failed: ${test.error}`}
        </p>
      )}
      {note && <p className="mt-1.5 doc-meta normal-case">{note}</p>}
    </div>
  );
};

const ModelSheet = ({ isAdmin }) => {
  const [models, setModels] = useState([]);
  const [fallback, setFallback] = useState('');
  const [tiers, setTiers] = useState({});
  const [catalog, setCatalog] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [openRow, setOpenRow] = useState(null); // at most one tier open at a time
  const toggle = (id) => () => setOpenRow((current) => (current === id ? null : id));

  useEffect(() => {
    let cancelled = false;
    // Only an admin can change the models, so only an admin needs the
    // gateway's full list and catalog for the picker.
    Promise.all([
      api.get(endpoints.settings.omnirouteModel),
      api.get(endpoints.settings.omnirouteTiers),
      ...(isAdmin ? [api.get(endpoints.settings.omnirouteModels), api.get(endpoints.settings.omnirouteCatalog)] : []),
    ])
      .then(([currentRes, tiersRes, modelsRes, catalogRes]) => {
        if (cancelled) return;
        setFallback(currentRes.data.model);
        setTiers(tiersRes.data.tiers);
        if (modelsRes) setModels(modelsRes.data);
        if (catalogRes) setCatalog(catalogRes.data);
      })
      .catch(() => {
        if (!cancelled) setLoadError('Could not reach the OmniRoute gateway.');
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const saveTier = (tier) => async (model) => {
    await api.post(endpoints.settings.omnirouteTiers, { tier, model });
    setTiers((current) => ({ ...current, [tier]: model }));
  };

  const saveFallback = async (model) => {
    await api.post(endpoints.settings.omnirouteModel, { model });
    setFallback(model);
  };

  // Deployment-wide: every user's requests run on these models, so the
  // server only lets an admin change them. Everyone else sees them locked.
  if (!isAdmin) {
    return (
      <Sheet title="Models" meta="Set by an admin">
        {loadError ? (
          <Empty title="Gateway unreachable" detail={loadError} />
        ) : !fallback ? (
          <Ruling rows={4} />
        ) : (
          <>
            <p className="text-sm text-[var(--ink-soft)] pb-1">
              The models are chosen by an admin for everyone using this app.
            </p>
            {[...TIER_ROWS, { id: 'fallback', label: 'Fallback', hint: 'Any task whose tier is not set' }].map((row) => (
              <Row key={row.id} label={row.label} hint={row.hint}>
                <span className="figure-md text-sm break-all">
                  {row.id === 'fallback' ? fallback : tiers[row.id] || `Fallback (${fallback})`}
                </span>
              </Row>
            ))}
          </>
        )}
      </Sheet>
    );
  }

  return (
    <Sheet title="Models" meta={`${models.length} available`}>
      {loadError ? (
        <Empty title="Gateway unreachable" detail={loadError} />
      ) : (
        <>
          <p className="text-sm text-[var(--ink-soft)]">
            Each kind of task runs on its own model, so cheap work does not spend the strongest model's quota.
            The trading engine itself never calls a model on the hot path.
          </p>
          {TIER_ROWS.map((row) => (
            <ModelRow
              key={row.id}
              label={row.label}
              hint={row.hint}
              value={tiers[row.id]}
              fallback={fallback}
              models={models}
              catalog={catalog}
              onSave={saveTier(row.id)}
              clearable
              expanded={openRow === row.id}
              onToggle={toggle(row.id)}
            />
          ))}
          <ModelRow
            label="Fallback"
            hint="Any task whose tier is not set"
            value={fallback}
            fallback={fallback}
            models={models}
            catalog={catalog}
            onSave={saveFallback}
            expanded={openRow === 'fallback'}
            onToggle={toggle('fallback')}
          />
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

/** "06:19" today, "07 Oct" later: when a pool fills back up. */
const resetText = (iso) => {
  if (!iso) return '';
  const when = new Date(iso);
  const sameDay = when.toDateString() === new Date().toDateString();
  return sameDay
    ? when.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })
    : when.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' });
};

const PoolRow = ({ pool }) => {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={!pool.models.length}
        aria-expanded={open}
        className="w-full flex items-center gap-2 py-1 text-left text-xs disabled:cursor-default"
      >
        <span className="w-[6.5rem] shrink-0 leading-tight text-[var(--ink)]">{pool.label}</span>
        <Bar pct={pool.remaining_pct} />
        <span className="figure-md w-[4.25rem] text-right shrink-0 whitespace-nowrap">{pctText(pool.remaining_pct)}</span>
      </button>
      <p className="doc-meta normal-case pl-[6.5rem] -mt-0.5">
        {pool.reset_at ? `resets ${resetText(pool.reset_at)}` : ''}
        {pool.models.length ? ` · ${pool.models.length} model${pool.models.length === 1 ? '' : 's'}` : ''}
      </p>
      {open && (
        <p className="pl-[6.5rem] pt-1 pb-1.5 text-xs text-[var(--ink-soft)] break-words">{pool.models.join(', ')}</p>
      )}
    </li>
  );
};

const ProviderRow = ({ provider }) => (
  <li className="py-2 border-b border-[var(--rule)] last:border-b-0">
    <p className="flex items-baseline gap-2 mb-1">
      <span className="figure-md text-sm">{provider.provider}</span>
      {provider.plan && <span className="doc-meta normal-case">{provider.plan}</span>}
    </p>
    <ul className="space-y-1">
      {provider.pools.map((pool) => (
        <PoolRow key={pool.label} pool={pool} />
      ))}
    </ul>
  </li>
);

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
            The gateway's shared accounts, not only this app's use. Models in one pool share its limit; tap a pool for its models.
          </p>
          <ul>
            {usage.providers
              .filter((provider) => provider.pools?.length)
              .map((provider) => (
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
  const [botToken, setBotToken] = useState('');
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);

  const loadTelegram = () =>
    api
      .get(endpoints.guardrails.status)
      .then((res) => setTelegram(res.data.telegram))
      .catch(() => setTelegram(null));

  useEffect(() => {
    api
      .get(endpoints.settings.preferences)
      .then((res) => {
        setPrefs(res.data);
        setDraft(Object.fromEntries(GUARD_FIELDS.map((key) => [key, res.data[key]])));
      })
      .catch(() => setPrefs(null));
    loadTelegram();
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
        onCommit={() => commit(key, Math.round(Number(draft[key])))}
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
          onChange={(value) => {
            setConfirmOff(false);
            setDraft((d) => ({ ...d, daily_loss_limit: value }));
          }}
          onCommit={() => commit('daily_loss_limit', Number(draft.daily_loss_limit))}
        />
      </Row>
      {confirmOff && (
        <div role="alert" className="py-2 flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--loss)]">
          <span>0 turns off the daily loss limit and the engine's kill-switch.</span>
          <span className="inline-flex gap-2">
            <button
              type="button"
              className="min-h-11 sm:min-h-0 px-2 py-1 border border-[var(--rule-strong)] text-[var(--ink)]"
              onClick={() => {
                setConfirmOff(false);
                setDraft((d) => ({ ...d, daily_loss_limit: prefs.daily_loss_limit }));
              }}
            >
              Keep {formatCurrency(prefs.daily_loss_limit)}
            </button>
            <button
              type="button"
              className="min-h-11 sm:min-h-0 px-2 py-1 border border-[var(--loss)]"
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
        label="Your Telegram bot"
        hint={
          telegram?.own_bot
            ? `Alerts come from @${telegram.own_bot}. Removing it unlinks your chat.`
            : 'Optional. In Telegram, message @BotFather, send /newbot, and paste the token it gives you. It is stored encrypted and never shown again.'
        }
      >
        {telegram?.own_bot ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => act(() => api.delete(endpoints.guardrails.telegramBot), () => {
              setLinkUrl(null);
              loadTelegram();
            })}
          >
            Remove bot
          </Button>
        ) : (
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              act(() => api.put(endpoints.guardrails.telegramBot, { token: botToken.trim() }), (res) => {
                setBotToken('');
                setLinkUrl(null);
                setTelegram((t) => ({ ...t, configured: true, linked: false, own_bot: res.data.own_bot }));
              });
            }}
          >
            <input
              type="password"
              autoComplete="off"
              value={botToken}
              onChange={(event) => setBotToken(event.target.value)}
              placeholder="123456:ABC…"
              aria-label="Telegram bot token"
              className="min-w-0 w-40 sm:w-56 bg-transparent border-b border-[var(--rule-strong)] py-1.5 text-sm focus:outline-none focus:border-[var(--stamp)]"
            />
            <Button type="submit" variant="primary" size="sm" disabled={busy || !botToken.trim()}>
              Save
            </Button>
          </form>
        )}
      </Row>

      <Row
        label="Telegram alerts"
        hint={
          telegram?.configured === false
            ? 'Add your own bot above to get alerts on your phone. They still appear in the app.'
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
      <Row
        label="News alerts"
        hint="Material news on the names you follow, as a toast here and on Telegram when linked. A market-wide shock reaches anyone holding something."
      >
        <div role="radiogroup" aria-label="News alerts" className="flex flex-wrap">
          {[
            ['held', 'Holdings'],
            ['held+watched', '+ Watchlist'],
            ['all', 'All'],
            ['off', 'Off'],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={(prefs.news_alerts || 'held') === value}
              onClick={() => value !== prefs.news_alerts && save({ news_alerts: value })}
              className={cn(
                'px-3 py-1 border -ml-px first:ml-0 font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors',
                (prefs.news_alerts || 'held') === value
                  ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
                  : 'text-[var(--ink-soft)] border-[var(--rule-strong)]'
              )}
            >
              {label}
            </button>
          ))}
        </div>
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
/** The way in to Profile from the phone, where Settings is the "More" tab. */
const ProfileRow = () => {
  const { user } = useAuth();
  const [displayName, setDisplayName] = useState(null);
  useEffect(() => {
    api.get(endpoints.profile.get).then((res) => setDisplayName(res.data.profile.display_name || null)).catch(() => {});
  }, []);
  return (
    <Link to="/profile" className="flex items-center gap-3 sheet px-3 py-2.5 sm:px-4 hover:bg-[var(--paper-sunk)] transition-colors">
      <Avatar src={user?.picture} name={displayName || user?.name} size={40} />
      <span className="flex-1 min-w-0">
        <span className="block text-sm font-semibold truncate">{displayName || user?.name || 'Your profile'}</span>
        <span className="block doc-meta normal-case truncate">Profile, AI instructions and memory</span>
      </span>
      <ArrowRight className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
    </Link>
  );
};

/** Practice -- the strategy engine -- lives under More: its decisions, engine, book and setup. */
const PracticeRow = () => {
  const pending = usePendingCount();
  return (
    <Link to="/practice/decisions" className="flex items-center gap-3 sheet px-3 py-2.5 sm:px-4 hover:bg-[var(--paper-sunk)] transition-colors">
      <span className="flex-1 min-w-0">
        <span className="block text-sm font-semibold">
          Practice
          {pending > 0 && (
            <span className="ml-1.5 figure-md px-1 text-[0.5625rem] leading-4 bg-[var(--stamp)] text-[var(--paper)]">{pending}</span>
          )}
        </span>
        <span className="block doc-meta normal-case truncate">The strategy engine: decisions, engine, book and setup</span>
      </span>
      <ArrowRight className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
    </Link>
  );
};

const LEGACY_TABS = { broker: 'accounts', guardrails: 'safety', portfolio: 'safety' };

const Settings = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [params, setParams] = useSearchParams();
  // Old links (?tab=broker, guardrails, portfolio) land on the regrouped tabs.
  useEffect(() => {
    const legacy = LEGACY_TABS[params.get('tab')];
    if (legacy) setParams({ tab: legacy }, { replace: true });
  }, [params, setParams]);
  const tabs = [
    { id: 'accounts', label: 'Accounts' },
    { id: 'safety', label: 'Safety' },
    { id: 'ai', label: 'AI' },
    { id: 'about', label: 'About' },
    ...(isAdmin ? [{ id: 'beta', label: 'Beta' }] : []),
  ];
  const [tab, setTab] = useTab(tabs.map((t) => t.id));
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <ProfileRow />
        <PracticeRow />
        <div>
          <Tabs tabs={tabs} active={tab} onSelect={setTab} label="Settings sections" />
          <div className="pt-3 sm:pt-4 space-y-3 sm:space-y-4">
            {tab === 'accounts' && <BrokerSheet />}
            {tab === 'safety' && (
              <>
                <GuardrailsSheet />
                <PortfolioSheet isAdmin={isAdmin} />
              </>
            )}
            {tab === 'ai' && (
              <>
                <ModelSheet isAdmin={isAdmin} />
                <Link
                  to="/ai/autopilot"
                  className="flex items-center justify-between gap-3 sheet px-3 py-2.5 sm:px-4 hover:bg-[var(--paper-sunk)] transition-colors"
                >
                  <span className="text-sm"><span className="field-label">Autopilot</span> switch and limits are under AI → Autopilot</span>
                  <ArrowRight className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
                </Link>
                {isAdmin && <UsageSheet />}
              </>
            )}
            {tab === 'about' && (
              <Link
                to="/system"
                className="flex items-center justify-between gap-3 sheet px-3 py-2.5 sm:px-4 hover:bg-[var(--paper-sunk)] transition-colors"
              >
                <span className="text-sm"><span className="field-label">How NeoTrade works</span> — a live view of the system</span>
                <ArrowRight className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
              </Link>
            )}
            {tab === 'beta' && isAdmin && <BetaSheet />}
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default Settings;
