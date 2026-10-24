// A short-lived cache in front of api.get, so the shell and a page asking for the same thing on one
// navigation, or a page you just left, cost one request instead of several (2026-10-24 load audit).

/**
 * Wraps `get(url, config)`: identical GETs (same user `key()`, url and params) in flight share one
 * request, and a repeat within `ttlMs` is answered from memory. `config.cache === false` always fetches.
 * A failure is never kept. `clear()` drops everything: call it after any write and on live events.
 */
export const makeGetCache = (get, { ttlMs, now = Date.now, key }) => {
  const entries = new Map(); // key -> { at, promise }
  return {
    get(url, config = {}) {
      if (config.cache === false) return get(url, config);
      const id = `${key()}|${url}|${config.params ? JSON.stringify(config.params) : ''}`;
      const hit = entries.get(id);
      if (hit && now() - hit.at < ttlMs) return hit.promise;
      const promise = get(url, config).catch((err) => {
        if (entries.get(id)?.promise === promise) entries.delete(id);
        throw err;
      });
      entries.set(id, { at: now(), promise });
      return promise;
    },
    clear() {
      entries.clear();
    },
  };
};
