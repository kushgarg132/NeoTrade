import { useEffect, useState } from 'react';
import api, { endpoints } from '../utils/api';

/** News summary per symbol ({SYM: entry}); one request per distinct symbol list, {} on failure. */
export default function useSymbolNews(symbols) {
  const key = [...new Set((symbols || []).filter(Boolean).map((s) => s.toUpperCase().replace(/\.NS$/, '')))]
    .sort().join(',');
  // Keyed by the symbol list: while a new list is in flight the old news stays and loading is true.
  const [state, setState] = useState({ key: '', news: {} });
  useEffect(() => {
    if (!key) return undefined;
    let live = true;
    api.get(endpoints.newsSymbols(key))
      .then((res) => live && setState({ key, news: res.data.symbols || {} }))
      .catch(() => live && setState({ key, news: {} }));
    return () => { live = false; };
  }, [key]);
  return key ? { news: state.news, loading: state.key !== key } : { news: {}, loading: false };
}
