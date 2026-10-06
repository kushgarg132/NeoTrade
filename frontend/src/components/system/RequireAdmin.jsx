import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

/** The handbook and backlog are the operator's own: anyone else goes to Settings. */
const RequireAdmin = ({ children }) => {
  const { user } = useAuth();
  return user?.role === 'admin' ? children : <Navigate to="/settings" replace />;
};

export default RequireAdmin;
