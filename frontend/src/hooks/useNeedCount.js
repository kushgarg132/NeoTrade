import { useCallback, useEffect, useState } from 'react';
import api, { endpoints } from '../utils/api';
import { useAuth } from '../context/AuthContext';
import { useReconnect, useTopic } from './useStream';
import { ideaFromSuggestion, ideaFromPick, needCount } from '../utils/ideas';

/** Pending ideas: your suggestions, plus the served Picks (`shown`), both admin-only (a Picks failure never hides the
 *  suggestions). Returns { items, hiddenReason, hiddenCount } (picks the server kept back: top 3 per grade). */
export const fetchIdeas = async (isAdmin) => {
  // Engine ideas are admin-only (the API 403s anyone else), so a non-admin never asks.
  const sug = isAdmin
    ? await api.get(endpoints.suggestions.list({ status: 'PENDING' })).then((r) => r.data.map(ideaFromSuggestion))
    : [];
  let hiddenReason = '';
  let hiddenCount = 0;
  const picks = isAdmin
    ? await api.get(endpoints.picks.today).then((r) => {
      hiddenReason = r.data.hidden_reason || '';
      hiddenCount = r.data.hidden_count || 0;
      return (r.data.shown || []).map((p) => ideaFromPick(p, r.data.setups.find((s) => s.setup === p.setup), r.data.grade_text));
    }).catch(() => [])
    : [];
  return { items: [...sug, ...picks], hiddenReason, hiddenCount };
};

/**
 * The one "needs you" count (Home line, Ideas tile, Ideas tab badge): { count, actions, ideas, loaded, error, reload }.
 * `count` is null until the first answer; a failed reload keeps the last good numbers and sets `error`
 * (a failure used to read as 0).
 */
export const useNeedCount = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const [s, setS] = useState(null);
  const [error, setError] = useState(false);
  const load = useCallback(() => {
    Promise.all([
      api.get(endpoints.mine.actions).then((r) => r.data).catch(() => null),
      fetchIdeas(isAdmin).then((r) => r.items).catch(() => null),
    ]).then(([actions, ideas]) => {
      if (actions === null || ideas === null) return setError(true);
      setS({ actions, ideas });
      setError(false);
    });
  }, [isAdmin]);
  useEffect(() => { load(); }, [load]);
  useReconnect(load);
  useTopic('suggestions', load);
  return {
    actions: s?.actions || [], ideas: s?.ideas || [], count: s ? needCount(s.actions, s.ideas) : null,
    loaded: s !== null, error, reload: load,
  };
};
