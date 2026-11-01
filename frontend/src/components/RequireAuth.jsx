import React from 'react';
import { useAuth } from '../context/AuthContext';
import Layout from './Layout';
import SignInCard from './SignInCard';

const RequireAuth = ({ children, title, body }) => {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--surface)]">
        <p className="field-label" role="status">
          Retrieving note…
        </p>
      </div>
    );
  }

  // Signed out: the card in place, URL untouched, so a broker's ?code= survives
  // sign-in and the page renders where the reader already is.
  if (!user) {
    return (
      <Layout>
        <SignInCard title={title ?? 'Sign in to use this'} body={body ?? 'Your accounts, money and AI live behind sign-in.'} />
      </Layout>
    );
  }

  return children;
};

export default RequireAuth;
