import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const RequireAuth = ({ children }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--paper)]">
        <p className="field-label" role="status">
          Retrieving note…
        </p>
      </div>
    );
  }

  // Carry the full location through sign-in: a broker redirect lands on
  // /settings?code=... and the code must survive the detour to /login.
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;

  return children;
};

export default RequireAuth;
