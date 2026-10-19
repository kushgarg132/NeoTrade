import React, { useEffect, useState } from 'react';
import { Search, Loader2, Check, ExternalLink, Unplug } from 'lucide-react';
import { Sheet, Empty, Ruling, Stamp, Button, Badge } from './Panel';
import api, { endpoints, getPreferences } from '../../utils/api';
import { cn } from '../../utils/cn';
import { useSearchParams } from 'react-router-dom';

const BROKER_TONE = {
  ACTIVE: 'success',
  NEEDS_LOGIN: 'warning',
  DEGRADED: 'destructive',
  UNCONFIGURED: 'secondary',
};

const BROKER_LABEL = { kite: 'Zerodha Kite', upstox: 'Upstox', angel_one: 'Angel One' };

const TextField = ({ id, label, ...props }) => (
  <div>
    <label htmlFor={id} className="text-[13px] font-medium text-[var(--text-muted)] block mb-1">
      {label}
    </label>
    <input
      id={id}
      autoComplete="off"
      className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-[12px] px-3 min-h-11 text-sm focus:outline-none focus:border-[var(--accent)]"
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
    getPreferences().then((res) => setRoles(res.data.broker_roles || {})).catch(() => setRoles({}));
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
    <div className="mt-3 pt-3 border-t border-[var(--border)]">
      <p className="text-[13px] font-medium text-[var(--text-muted)] mb-1.5">This account is</p>
      <div role="radiogroup" aria-label="Account role" className="grid grid-cols-2 gap-2">
        {ROLE_OPTIONS.map(([role, label, hint]) => (
          <button
            key={role}
            type="button"
            role="radio"
            aria-checked={roles[broker] === role}
            onClick={() => choose(role)}
            className={cn(
              'text-left p-3 rounded-[12px] border transition-colors min-h-11',
              roles[broker] === role ? 'border-[var(--accent)] bg-[var(--accent-soft)]' : 'border-[var(--border)] bg-[var(--surface)]',
            )}
          >
            <span className="block text-[15px] font-semibold text-[var(--text)]">{label}</span>
            <span className="block text-[13px] text-[var(--text-muted)] mt-0.5">{hint}</span>
          </button>
        ))}
      </div>
      {note && <p className="text-[13px] text-[var(--loss)] mt-1.5">{note}</p>}
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
    } catch (err) {
      setNote(err?.response?.data?.detail || 'Could not disconnect');
    } finally {
      setBusy(false);
    }
  };

  const brokerPicker = (
    <div className="flex flex-wrap gap-1.5">
      {Object.keys(BROKER_LABEL).map((key) => (
        <button
          key={key}
          type="button"
          onClick={() => setBroker(key)}
          className={cn(
            'min-h-11 px-3 rounded-full border text-[14px] font-semibold',
            key === broker
              ? 'border-transparent bg-[var(--accent-soft)] text-[var(--accent)]'
              : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)]',
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
      <p className="text-sm text-[var(--text-muted)]">
        A connected {BROKER_LABEL[broker]} session imports your trades into the journal and lets
        guardrails check your account.{' '}
        {broker === 'angel_one'
          ? 'Intraday runs still use delayed quotes — live ticks from Angel One aren’t supported yet.'
          : 'It also supplies live tick data for intraday runs.'}{' '}
        On your own account a real order goes out only when you confirm one (Ideas, the order
        ticket, the chat), or from a guardrail square-off you’ve set to Live. On the AI account,
        only when its autopilot is Live.
      </p>
      {state.state !== 'UNCONFIGURED' && <BrokerRole broker={broker} />}

      {state.state === 'UNCONFIGURED' ? (
        <div className="mt-4 space-y-3">
          <p className="text-[13px] text-[var(--text-muted)]">
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
          <p className="text-[13px] text-[var(--text-muted)]">Sessions end at midnight IST.</p>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <Button variant="primary" size="sm" onClick={openLogin} disabled={busy}>
            <ExternalLink className="w-3.5 h-3.5" />
            Connect {BROKER_LABEL[broker]}
          </Button>

          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor="request-token" className="text-[13px] font-medium text-[var(--text-muted)] block mb-1">
                {broker === 'upstox' ? 'Code' : 'Request token'}
              </label>
              <input
                id="request-token"
                value={requestToken}
                onChange={(event) => setRequestToken(event.target.value)}
                placeholder="From the redirect URL after login"
                className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-[12px] px-3 min-h-11 text-sm focus:outline-none focus:border-[var(--accent)]"
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

          <p className="text-[13px] text-[var(--text-muted)]">
            {broker === 'kite'
              ? 'The token is single-use and expires in minutes. Sessions end daily at 6:00 AM IST.'
              : 'The code is single-use and expires in minutes. Sessions end daily at 3:30 AM IST.'}
          </p>
        </div>
      )}

      {note && <p className="mt-3 text-sm text-[var(--text-muted)]">{note}</p>}
    </Sheet>
  );
};

export default BrokerSheet;
