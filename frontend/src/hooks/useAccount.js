import { useEffect, useState } from 'react';
import { getPreferences } from '../utils/api';

const KEY = 'neotrade_account';
const read = () => {
  try {
    return localStorage.getItem(KEY) || 'all';
  } catch {
    return 'all';
  }
};

/** Which account a page shows: both, the AI's, or the user's own
    (backend/brokers/roles.py). Remembered per viewer; hidden until roles are set.
    `account` is null until the roles load: a page fetches nothing until then,
    so a Mine page never shows every account's money first. */
export const useAccount = (locked = null) => {
  const [account, setAccountState] = useState(read);
  const [roles, setRoles] = useState(null);
  useEffect(() => {
    getPreferences().then((res) => setRoles(res.data.broker_roles || {})).catch(() => setRoles({}));
  }, []);
  const setAccount = (value) => {
    setAccountState(value);
    try {
      localStorage.setItem(KEY, value);
    } catch {
      /* private mode: not remembered */
    }
  };
  if (roles === null) return { account: null, setAccount, roles, hasBoth: false, locked, hasRole: false };
  const hasBoth = roles && Object.values(roles).includes('ai') && Object.values(roles).includes('mine');
  if (locked) {
    const hasRole = roles && Object.values(roles).includes(locked);
    return { account: hasRole ? locked : 'all', setAccount, roles, hasBoth: false, locked, hasRole };
  }
  return { account: hasBoth ? account : 'all', setAccount, roles, hasBoth };
};
