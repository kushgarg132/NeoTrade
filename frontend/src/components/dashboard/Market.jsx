import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sheet, Statement, Row, Cell, Ruling, Scrip } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { formatSignedPercent, formatNoteDate, bareSymbol, formatLevel } from '../../utils/formatters';
import { cn } from '../../utils/cn';
import { stockPath } from '../../utils/stocks';

/**
 * Market context, printed as one appendix rather than competing widgets:
 * the indices and the day's NIFTY 50 gainers and losers.
 */

/** An index name that opens its detail on the statement, the way a scrip does. */
const IndexName = ({ item }) => (
  <Link
    to="/research"
    state={{ index: item.symbol }}
    onClick={(event) => event.stopPropagation()}
    className="text-sm underline decoration-[var(--rule)] decoration-1 underline-offset-[3px] hover:decoration-[var(--stamp)] hover:text-[var(--stamp)] transition-colors"
    aria-label={`Open ${item.name}`}
  >
    {item.name}
  </Link>
);

const Quote = ({ item, onClick, index = false }) => (
  <Row className={onClick && 'cursor-pointer hover:bg-[var(--paper-sunk)]'} onClick={onClick}>
    <Cell>
      {index ? (
        <IndexName item={item} />
      ) : (
        <Scrip symbol={item.symbol} className="text-sm font-normal">
          {/* The movers feed names each scrip by its Yahoo ticker. */}
          {item.name && item.name !== item.symbol ? item.name : bareSymbol(item.symbol)}
        </Scrip>
      )}
    </Cell>
    <Cell align="right" mono>
      {formatLevel(item.value)}
    </Cell>
    <Cell align="right">
      <span className={cn('figure-md text-sm', item.percent >= 0 ? 'text-up' : 'text-down')}>
        {formatSignedPercent(item.percent)}
      </span>
    </Cell>
  </Row>
);

/** One side of the movers: name, then last price and change, compact enough for two columns on a phone. */
const MoverList = ({ title, items, onOpen }) => (
  <div className="min-w-0">
    <p className="field-label mb-1">{title}</p>
    {items.length === 0 ? (
      <p className="doc-meta normal-case py-2">None today.</p>
    ) : (
      <ul>
        {items.map((item) => (
          <li key={item.symbol} className="border-b border-[var(--rule)] last:border-b-0">
            <button
              type="button"
              onClick={() => onOpen(item.symbol)}
              className="w-full text-left py-2 min-h-11 hover:bg-[var(--paper-sunk)] transition-colors"
            >
              <span className="figure-md text-sm block truncate underline decoration-[var(--rule)] underline-offset-[3px]">
                {item.name && item.name !== item.symbol ? item.name : bareSymbol(item.symbol)}
              </span>
              <span className="flex items-baseline justify-between gap-2 text-xs">
                <span className="figure-md text-[var(--ink-soft)]">{formatLevel(item.value)}</span>
                <span className={cn('figure-md', item.percent >= 0 ? 'text-up' : 'text-down')}>
                  {formatSignedPercent(item.percent)}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    )}
  </div>
);

const Market = () => {
  const navigate = useNavigate();
  // Each feed is shown the moment it arrives; null means still loading.
  const [data, setData] = useState({ indices: null, global: null, trending: null });

  useEffect(() => {
    const feeds = [
      ['indices', endpoints.marketIndices, (res) => res.data],
      ['global', endpoints.globalIndices, (res) => res.data],
      ['trending', endpoints.trendingStocks, (res) => res.data],
    ];
    let live = true;
    feeds.forEach(([key, url, pick]) => {
      api
        .get(url)
        .then((res) => pick(res))
        .catch(() => [])
        .then((value) => live && setData((current) => ({ ...current, [key]: value })));
    });
    return () => {
      live = false;
    };
  }, []);

  // Indian indices first; the world ones one tap away.
  const [world, setWorld] = useState(false);
  const quotes = [...(data.indices || []), ...(world ? data.global || [] : [])];
  const quotesLoading = data.indices === null && data.global === null;
  const done = Object.values(data).every((value) => value !== null);
  if (done && quotes.length === 0 && data.trending.length === 0) return null;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {quotesLoading && (
        <Sheet title="Indices">
          <Ruling rows={4} />
        </Sheet>
      )}
      {quotes.length > 0 && (
        <Sheet title="Indices" meta={formatNoteDate()}>
          <Statement
            inline
            columns={[
              { key: 'name', label: 'Index' },
              { key: 'value', label: 'Level', align: 'right' },
              { key: 'change', label: 'Change', align: 'right' },
            ]}
          >
            {quotes.map((item) => (
              <Quote
                key={item.symbol || item.name}
                item={item}
                index
                onClick={() => navigate('/research', { state: { index: item.symbol } })}
              />
            ))}
          </Statement>
          {data.global?.length > 0 && (
            <button
              type="button"
              onClick={() => setWorld((value) => !value)}
              aria-expanded={world}
              className="mt-1 field-label text-[var(--stamp)] hover:underline min-h-11 sm:min-h-0"
            >
              {world ? 'India only' : `World › ${data.global.length}`}
            </button>
          )}
        </Sheet>
      )}

      {data.trending === null && (
        <Sheet title="Movers" meta="NIFTY 50">
          <Ruling rows={4} />
        </Sheet>
      )}
      {data.trending?.length > 0 && (
        <Sheet title="Movers" meta="NIFTY 50">
          <div className="grid grid-cols-2 gap-4">
            <MoverList title="Gainers" items={data.trending.filter((m) => m.percent > 0)}
              onOpen={(symbol) => navigate(stockPath(symbol))} />
            <MoverList title="Losers" items={data.trending.filter((m) => m.percent < 0)}
              onOpen={(symbol) => navigate(stockPath(symbol))} />
          </div>
        </Sheet>
      )}
    </div>
  );
};

export default Market;
