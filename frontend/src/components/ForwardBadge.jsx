import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Badge } from './common/Badge';
import api, { endpoints } from '../utils/api';
import { badgeFor } from '../utils/forward';

// One scorecard fetch shared by every badge on a page.
// ponytail: 30 s TTL, no invalidation.
let cached = null;
const load = () => {
  if (!cached || Date.now() - cached.at > 30000) {
    cached = { at: Date.now(), p: api.get(endpoints.forward.scorecard).then((res) => res.data.rows).catch(() => []) };
  }
  return cached.p;
};

/** Scorecard rows for admins; [] for everyone else and on any error (the badge stays hidden). */
// eslint-disable-next-line react-refresh/only-export-components
export const useForward = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const [rows, setRows] = useState([]);
  useEffect(() => {
    if (isAdmin) load().then(setRows);
  }, [isAdmin]);
  return rows;
};

/** Proven / Unproven n/100 for one (source, name) from the forward record. */
const ForwardBadge = ({ source, name }) => {
  const b = badgeFor(useForward(), source, name);
  return b ? <Badge variant={b.tone}>{b.text}</Badge> : null;
};

export default ForwardBadge;
