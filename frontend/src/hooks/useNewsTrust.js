import { useSyncExternalStore } from 'react';
import api, { endpoints } from '../utils/api';
import { newsTrust, setNewsTrust, subscribeNewsTrust } from '../utils/newsTrust';

let loading = null;

/** Fetches GET /news/trust once per page load (Layout calls it at boot); a failure keeps calls hidden. */
export const loadNewsTrust = () => {
  loading ||= api.get(endpoints.newsTrust).then((res) => setNewsTrust(res.data)).catch(() => {});
  return loading;
};

/** { trusted, line, scorer, all }; re-renders when it loads. */
export const useNewsTrust = () => useSyncExternalStore(subscribeNewsTrust, newsTrust);
