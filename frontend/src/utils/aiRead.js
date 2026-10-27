export const AI_EMPTY = {
  symbol: null, read: null, at: null, stale: false, stage: null,
  text: '', streaming: false, error: null, loading: true,
};

export function aiReducer(state, { symbol, event, data }) {
  if (event === 'reset') return { ...AI_EMPTY, symbol };
  if (symbol !== state.symbol) return state;
  switch (event) {
    case 'cached': {
      const read = data?.read ?? null;
      const stale = !!data?.stale;
      return { ...state, read, at: data?.at ?? null, stale, loading: stale && !read };
    }
    case 'stage':
      return { ...state, stage: data, streaming: true };
    case 'delta':
      return { ...state, text: state.text + data.text, streaming: true };
    case 'report':
      return { ...state, read: data, at: new Date().toISOString(), stale: false, stage: null, text: '', streaming: false, error: null };
    case 'error':
      return { ...state, error: data.detail, text: '', stage: null, streaming: false };
    case 'done':
      return { ...state, loading: false, streaming: false };
    default:
      return state;
  }
}

const MARKER = '===THESIS===';

export function splitThesis(text) {
  const i = text.indexOf(MARKER);
  if (i >= 0) return { summary: text.slice(0, i).trimEnd(), thesis: text.slice(i + MARKER.length).trimStart() };
  for (let n = MARKER.length - 1; n > 0; n--) {
    if (text.endsWith(MARKER.slice(0, n))) return { summary: text.slice(0, -n).trimEnd(), thesis: '' };
  }
  return { summary: text, thesis: '' };
}
