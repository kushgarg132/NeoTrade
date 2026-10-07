import React, { useEffect, useState } from 'react';
import { Search, X } from 'lucide-react';
import { Badge } from '../common/Badge';
import { StockIcon } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';


/**
 * An intraday run's standing instructions, filled in before it starts.
 * Long-term ideas come from the daily scan, not a run, so there is no
 * horizon to choose here.
 */
const TradingControlBar = ({
  universeSymbols,
  onUniverseChange,
  accountSize,
  onAccountSizeChange,
  maxExposure,
  onMaxExposureChange,
  startError,
}) => {
  const [query, setQuery] = useState('');
  const [matches, setMatches] = useState([]);

  useEffect(() => {
    const term = query.trim();
    const handle = setTimeout(async () => {
      if (term.length < 2) {
        setMatches([]);
        return;
      }
      try {
        const res = await api.get(endpoints.trading.instruments(term));
        setMatches(res.data.slice(0, 6));
      } catch {
        setMatches([]);
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  const add = (symbol) => {
    if (!universeSymbols.includes(symbol)) onUniverseChange([...universeSymbols, symbol]);
    setQuery('');
    setMatches([]);
  };

  return (
    <div className="space-y-5">
      <p className="doc-meta normal-case">Intraday · signals execute without approval, squared off by 3:15 PM.</p>

      <div className="relative">
        <label htmlFor="universe-search" className="field-label block mb-1.5">
          Universe{' '}
          {universeSymbols.length === 0 && (
            <span className="text-[var(--ink-faint)]">— default, 83 scrip</span>
          )}
        </label>
        <div className="flex items-center gap-2 border-b border-[var(--rule-strong)] focus-within:border-[var(--stamp)]">
          <Search className="w-4 h-4 shrink-0 text-[var(--ink-faint)]" />
          <input
            id="universe-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Add a scrip"
            autoComplete="off"
            className="w-full bg-transparent border-0 py-2 text-sm focus:outline-none"
          />
        </div>

        {matches.length > 0 && (
          <ul className="absolute z-[35] left-0 right-0 mt-px sheet max-h-56 overflow-y-auto">
            {matches.map((match) => (
              <li key={match.instrument_token}>
                <button
                  type="button"
                  onClick={() => add(match.tradingsymbol)}
                  className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left border-b border-[var(--rule)] last:border-b-0 hover:bg-[var(--stamp-soft)]"
                >
                  <span className="figure-md text-sm inline-flex items-center gap-1.5">
                    <StockIcon symbol={match.tradingsymbol} />
                    {match.tradingsymbol}
                  </span>
                  <span className="text-xs text-[var(--ink-soft)] truncate">{match.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {universeSymbols.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {universeSymbols.map((symbol) => (
              <Badge key={symbol} variant="default" className="gap-1.5 pr-1">
                {symbol}
                <button
                  type="button"
                  onClick={() => onUniverseChange(universeSymbols.filter((s) => s !== symbol))}
                  className="hover:text-[var(--loss)]"
                  aria-label={`Remove ${symbol}`}
                >
                  <X className="w-3 h-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label htmlFor="account-size" className="field-label block mb-1.5">
            Account size
          </label>
          <input
            id="account-size"
            type="number"
            inputMode="numeric"
            value={accountSize}
            onChange={(event) => onAccountSizeChange(Number(event.target.value))}
            className="w-full bg-transparent border-b border-[var(--rule-strong)] py-1.5 figure-md text-sm focus:outline-none focus:border-[var(--stamp)]"
          />
        </div>
        <div>
          <label htmlFor="max-exposure" className="field-label block mb-1.5">
            Max exposure
          </label>
          <input
            id="max-exposure"
            type="number"
            inputMode="numeric"
            value={maxExposure}
            onChange={(event) => onMaxExposureChange(Number(event.target.value))}
            className="w-full bg-transparent border-b border-[var(--rule-strong)] py-1.5 figure-md text-sm focus:outline-none focus:border-[var(--stamp)]"
          />
        </div>
      </div>

      {startError && (
        <p
          role="alert"
          className="text-sm text-[var(--loss)] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2"
        >
          {startError}
        </p>
      )}
    </div>
  );
};

export default TradingControlBar;
