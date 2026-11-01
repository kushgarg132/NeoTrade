import React, { useState } from 'react';
import { GoogleLogin } from '@react-oauth/google';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/useTheme';
import Card from './ui/Card';

/** Google sign-in button plus its error. Navigation is the caller's job via `onDone`. */
export const GoogleButton = ({ onDone }) => {
  const { login } = useAuth();
  const { theme } = useTheme();
  const [error, setError] = useState('');

  const onSuccess = async (credentialResponse) => {
    try {
      await login(credentialResponse.credential);
      onDone?.();
    } catch {
      setError('Sign-in failed. Try again.');
    }
  };

  return (
    <>
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
      {error && (
        <p
          role="alert"
          className="mt-4 text-sm text-center text-[var(--loss)] rounded-[12px] bg-[var(--loss-soft)] px-3 py-2"
        >
          {error}
        </p>
      )}
    </>
  );
};

/** Inline prompt shown in place of a locked page. */
const SignInCard = ({ title, body }) => (
  <Card title={title}>
    <p className="text-sm text-[var(--text-muted)] mb-4">{body}</p>
    <GoogleButton />
    <p className="mt-4 text-xs text-[var(--text-muted)] text-center">Free while in beta. Not investment advice.</p>
  </Card>
);

export default SignInCard;
