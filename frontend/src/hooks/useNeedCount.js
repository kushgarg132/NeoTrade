import { useCallback, useEffect, useState } from 'react';
import api, { endpoints } from '../utils/api';
import { useAuth } from '../context/AuthContext';
import { useReconnect, useTopic } from './useStream';
import { ideaFromSuggestion, ideaFromPick, needCount } from '../utils/ideas';

/** Pending ideas: your suggestions, plus the served Picks (`shown`) for admins (a Picks failure never hides the
 *  suggestions). Returns { items, hiddenReason }. */
export const fetchIdeas = async (isAdmin) => {
  const sug = await api.get(endpoints.suggestions.list({ status: 'PENDING' })).then((r) => r.data.map(ideaFromSuggestion));
  let hiddenReason = '';
  const picks = isAdmin
    ? await api.get(endpoints.picks.today).then((r) => {
      hiddenReason = r.data.hidden_reason || '';
      return (r.data.shown || []).map((p) => ideaFromPick(p, r.data.setups.find((s) => s.setup === p.setup)));
    }).catch(() => [])
    : [];
  return { items: [...sug, ...picks], hiddenReason };
};

/** The one "needs you" count (Home line, Ideas tile, Ideas tab badge): { count, actions, ideas }. */
export const useNeedCount = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const [s, setS] = useState({ actions: [], ideas: [] });
  const load = useCallback(() => {
    Promise.all([
      api.get(endpoints.mine.actions).then((r) => r.data).catch(() => []),
      fetchIdeas(isAdmin).then((r) => r.items).catch(() => []),
    ]).then(([actions, ideas]) => setS({ actions, ideas }));
  }, [isAdmin]);
  useEffect(() => { load(); }, [load]);
  useReconnect(load);
  useTopic('suggestions', load);
  return { ...s, count: needCount(s.actions, s.ideas) };
};
