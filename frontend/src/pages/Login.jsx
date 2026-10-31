import React, { useState } from 'react';
import { GoogleLogin } from '@react-oauth/google';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/useTheme';
import Badge from '../components/ui/Badge';
import { LogoMark } from '../components/layout/Logo';

/** Sign-in: one line on what NeoTrade is, then Google sign-in. */
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
    <div className="min-h-screen bg-[var(--bg)] flex items-center justify-center p-4">
      <div
        className="w-full max-w-sm rounded-[28px] border border-[var(--border)] p-6"
        style={{ background: 'var(--glow)' }}
      >
        <LogoMark size={56} className="text-[var(--text)] mb-4" />
        <h1 className="text-[44px] font-extrabold tracking-[-0.04em] leading-none text-[var(--text)]">NeoTrade</h1>
        <p className="text-[15px] text-[var(--text)] mt-3">
          Your broker account, reviewed daily. Plus an AI account that trades on paper until a
          strategy proves itself.
        </p>
        <div className="mt-3">
          <Badge kind="paper">Paper until proven</Badge>
        </div>
        <p className="text-sm text-[var(--text-muted)] mt-3 mb-6">
          Works with Zerodha, Upstox and Angel One.
        </p>

          {/* Google's iframe is light; under the page's dark color-scheme the browser paints it an opaque white backdrop. */}
          <div className="flex justify-center [color-scheme:light]">
            <GoogleLogin
              onSuccess={onSuccess}
              onError={() => setError('Sign-in failed. Try again.')}
              theme={theme === 'dark' ? 'filled_black' : 'outline'}
              shape="square"
              width="280"
            />
          </div>

          {brokerCode && (
            <p className="mt-5 text-sm text-[var(--text-muted)] text-center">
              Sign in to finish connecting your broker. Your login code:{' '}
              <span className="select-all break-all text-[var(--text)]">{brokerCode}</span>
            </p>
          )}

          {error && (
            <p
              role="alert"
              className="mt-4 text-sm text-center text-[var(--loss)] rounded-[12px] bg-[var(--loss-soft)] px-3 py-2"
            >
              {error}
            </p>
          )}

        <p className="mt-6 pt-4 border-t border-[var(--border)] text-xs text-[var(--text-muted)] text-center">
          Free while in beta. Not investment advice. NeoTrade never holds your money.
        </p>
      </div>
    </div>
  );
};

export default Login;
