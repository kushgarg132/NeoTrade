import React, { useEffect, useRef, useState } from 'react';
import { Search, Loader2 } from 'lucide-react';
import api, { endpoints } from '../../utils/api';
import { cn } from '../../utils/cn';
import { StockIcon } from '../doc/Doc';
import { formatCurrency, formatSignedPercent } from '../../utils/formatters';

/**
 * Instrument lookup against the NSE master. Typeahead rather than blind
 * submit: the operator knows the company, not always the tradingsymbol, and
 * guessing wrong used to cost a full analysis round trip to find out.
 *
 * Keyboard-complete because a search you cannot drive from the keyboard is a
 * search you retype.
 */
const SmartSearch = ({ onSearch, isLoading, className }) => {
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [searching, setSearching] = useState(false);
  const [quotes, setQuotes] = useState({});
  const quoteRequest = useRef(0);
  const boxRef = useRef(null);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) {
      setMatches([]);
      setSearching(false);
      return undefined;
    }
    setSearching(true);
    const handle = setTimeout(async () => {
      try {
        const res = await api.get(endpoints.trading.instruments(term));
        const top = res.data.slice(0, 7);
        setMatches(top);
        setActive(0);
        // Prices fill in when they arrive; typing never waits on them, and
        // a slower answer for an older query is dropped.
        const request = ++quoteRequest.current;
        if (top.length) {
          api
            .get(endpoints.marketQuotes(top.map((m) => m.tradingsymbol)))
            .then((q) => {
              if (request === quoteRequest.current) {
                setQuotes(Object.fromEntries(q.data.map((row) => [row.symbol, row])));
              }
            })
            .catch(() => {});
        }
      } catch {
        setMatches([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    const onClickAway = (event) => {
      if (boxRef.current && !boxRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickAway);
    return () => document.removeEventListener('mousedown', onClickAway);
  }, []);

  const choose = (symbol) => {
    setQuery('');
    setMatches([]);
    setOpen(false);
    onSearch(symbol);
  };

  const onKeyDown = (event) => {
    if (!open || matches.length === 0) {
      if (event.key === 'Enter' && query.trim()) choose(query.trim().toUpperCase());
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => (i + 1) % matches.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => (i - 1 + matches.length) % matches.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(matches[active].tradingsymbol);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  };

  const showList = open && (matches.length > 0 || (query.trim().length >= 2 && !searching));

  return (
    <div ref={boxRef} className={cn('relative', className)}>
      <label htmlFor="instrument-search" className="field-label block mb-1.5">
        Scrip enquiry
      </label>
      <div className="flex items-center gap-2 border-b-2 border-[var(--rule-strong)] focus-within:border-[var(--stamp)] transition-colors">
        {isLoading || searching ? (
          <Loader2 className="w-4 h-4 shrink-0 text-[var(--stamp)] animate-spin" />
        ) : (
          <Search className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
        )}
        <input
          id="instrument-search"
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls="instrument-matches"
          aria-autocomplete="list"
          autoComplete="off"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Company or symbol"
          disabled={isLoading}
          className="w-full bg-transparent border-0 py-2.5 text-base focus:outline-none focus:ring-0 disabled:opacity-50"
        />
      </div>

      {showList && (
        <ul
          id="instrument-matches"
          role="listbox"
          className="absolute z-[35] left-0 right-0 mt-px sheet max-h-72 overflow-y-auto"
        >
          {matches.length === 0 ? (
            <li className="px-3 py-3 text-sm text-[var(--ink-soft)]">
              No scrip matches “{query.trim()}”.
            </li>
          ) : (
            matches.map((match, index) => (
              <li key={match.instrument_token} role="option" aria-selected={index === active}>
                <button
                  type="button"
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(match.tradingsymbol)}
                  className={cn(
                    'w-full text-left px-3 py-2.5 flex items-center justify-between gap-3 border-b border-[var(--rule)] last:border-b-0',
                    index === active ? 'bg-[var(--stamp-soft)]' : 'bg-transparent'
                  )}
                >
                  <span className="figure-md text-sm shrink-0 inline-flex items-center gap-1.5">
                    <StockIcon symbol={match.tradingsymbol} />
                    {match.tradingsymbol}
                  </span>
                  <span className="text-xs text-[var(--ink-soft)] truncate text-right flex-1 min-w-0">
                    {match.name}
                  </span>
                  {quotes[match.tradingsymbol] && (
                    <span className="shrink-0 text-right">
                      <span className="figure-md text-xs block">{formatCurrency(quotes[match.tradingsymbol].price)}</span>
                      <span
                        className={cn(
                          'figure-md text-[0.625rem] block',
                          quotes[match.tradingsymbol].change_pct >= 0 ? 'text-up' : 'text-down'
                        )}
                      >
                        {formatSignedPercent(quotes[match.tradingsymbol].change_pct)}
                      </span>
                    </span>
                  )}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
};

export default SmartSearch;
