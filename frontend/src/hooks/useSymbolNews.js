import { useEffect, useState } from 'react';
import api, { endpoints } from '../utils/api';

/** News summary per symbol ({SYM: entry}); one request per distinct symbol list, {} on failure. */
export default function useSymbolNews(symbols) {
  const key = [...new Set((symbols || []).filter(Boolean).map((s) => s.toUpperCase().replace(/\.NS$/, '')))]
    .sort().join(',');
  const [state, setState] = useState({ news: {}, loading: !!key });
  useEffect(() => {
    if (!key) { setState({ news: {}, loading: false }); return undefined; }
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    api.get(endpoints.newsSymbols(key))
      .then((res) => live && setState({ news: res.data.symbols || {}, loading: false }))
      .catch(() => live && setState({ news: {}, loading: false }));
    return () => { live = false; };
  }, [key]);
  return state;
}
