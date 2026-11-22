// Whether news up/down calls may be shown (GET /news/trust, backend/datalayer/accuracy.py::trust_status).
// Until the pinned news scorer is measured right often enough, every view shows headlines and impact
// but no direction: arrows, green/red, "bad news", lean filters. Unknown (not loaded, or failed) = hidden.

let state = { trusted: false, line: null };
const listeners = new Set();

export const newsTrust = () => state;

export const setNewsTrust = (next) => {
  state = { trusted: !!next?.trusted, line: next?.line ?? null, scorer: next?.scorer ?? null, all: next?.all ?? null };
  listeners.forEach((listener) => listener());
};

export const subscribeNewsTrust = (listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** A scorer's direction as -1 / 0 / 1, or 0 while its calls are not shown. */
export const lean = (direction) =>
  state.trusted && typeof direction === 'number' && Number.isFinite(direction) ? Math.sign(direction) : 0;
