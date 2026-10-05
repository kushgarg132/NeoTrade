import React, { useState } from 'react';
import { GoogleLogin } from '@react-oauth/google';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/useTheme';
import { formatNoteDate } from '../utils/formatters';

/** The cover sheet: what NeoTrade does for a trader, then Google sign-in. */
const Login = () => {
  const { login } = useAuth();
  const { theme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState('');

  // Where RequireAuth sent us from, query string included.
  const from = location.state?.from;
  // Or ?next= from a session that expired; same-site paths only ('//x' is another site).
  const next = new URLSearchParams(location.search).get('next');
  const safeNext = next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : null;
  const returnTo = from ? `${from.pathname}${from.search || ''}` : safeNext || '/';
  const params = new URLSearchParams(from?.search || '');
  const brokerCode = params.get('code') || params.get('request_token');

  const onSuccess = async (credentialResponse) => {
    try {
      await login(credentialResponse.credential);
      navigate(returnTo, { replace: true });
    } catch {
      setError('Sign-in failed. Try again.');
    }
  };

  return (
    <div className="min-h-screen bg-[var(--paper-sunk)] flex items-center justify-center p-4">
      <div className="w-full max-w-sm sheet">
        <div className="px-6 py-5 border-b border-[var(--rule-strong)] text-center">
          <h1 className="font-[family-name:var(--font-narrow)] font-bold uppercase tracking-[0.2em] text-sm">
            Contract Note
          </h1>
          <p className="doc-meta mt-1.5">NeoTrade · NSE · {formatNoteDate()}</p>
        </div>

        <div className="px-6 py-8">
          <p className="text-sm text-[var(--ink)] mb-5">
            A journal and guardrails for your own trading, on top of the broker you already use.
          </p>
          <dl className="space-y-4 mb-8">
            {[
              ['Journal', 'Every trade from Zerodha, Upstox or Angel One, imported for you, on a calendar of daily P&L.'],
              ['Patterns', 'Where your money actually goes: time of day, trading after losses, sizing up, holding losers.'],
              ['Guardrails', 'Your own loss limit, trade cap and cooldown, checked every minute, alerted on your phone.'],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="field-label">{label}</dt>
                <dd className="text-sm text-[var(--ink-soft)] mt-0.5">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="flex justify-center">
            <GoogleLogin
              onSuccess={onSuccess}
              onError={() => setError('Sign-in failed. Try again.')}
              theme={theme === 'dark' ? 'filled_black' : 'outline'}
              shape="square"
              width="280"
            />
          </div>

          {brokerCode && (
            <p className="mt-5 doc-meta normal-case text-center">
              Sign in to finish connecting your broker. Your login code:{' '}
              <span className="select-all break-all text-[var(--ink)]">{brokerCode}</span>
            </p>
          )}

          {error && (
            <p
              role="alert"
              className="mt-4 text-sm text-center text-[var(--loss)] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2"
            >
              {error}
            </p>
          )}
        </div>

        <p className="px-6 py-3 border-t border-[var(--rule)] doc-meta text-center normal-case">
          Free while in beta. Not investment advice. NeoTrade never holds your money.
        </p>
      </div>
    </div>
  );
};

export default Login;
