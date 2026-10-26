import { useEffect, useState } from 'react';
import api, { endpoints } from '../utils/api';

/** One GET per distinct symbol list, returning `res.data[field]` ({SYM: value}); {} on failure. */
const useBySymbol = (symbols, url, field) => {
  const key = [...new Set((symbols || []).filter(Boolean).map((s) => s.toUpperCase().replace(/\.NS$/, '')))]
    .sort().join(',');
  // Keyed by the symbol list: while a new list is in flight the old data stays and loading is true.
  const [state, setState] = useState({ key: '', data: {} });
  useEffect(() => {
    if (!key) return undefined;
    let live = true;
    api.get(url(key))
      .then((res) => live && setState({ key, data: res.data[field] || {} }))
      .catch(() => live && setState({ key, data: {} }));
    return () => { live = false; };
  }, [key, url, field]);
  return key ? { data: state.data, loading: state.key !== key } : { data: {}, loading: false };
};

/** News summary per symbol ({SYM: entry}) from GET /news/symbols. */
export default function useSymbolNews(symbols) {
  const { data, loading } = useBySymbol(symbols, endpoints.newsSymbols, 'symbols');
  return { news: data, loading };
}

/** Next results date per symbol ({SYM: 'YYYY-MM-DD'}) from GET /news/results (held stocks only). */
export function useSymbolResults(symbols) {
  return useBySymbol(symbols, endpoints.newsResults, 'results').data;
}
