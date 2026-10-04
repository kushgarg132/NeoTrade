import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sheet, Statement, Row, Cell, Ruling, Scrip } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { formatSignedPercent, formatNoteDate, formatTimeAgo, bareSymbol, formatLevel } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * Market context, printed as one appendix rather than four competing widgets:
 * the indices, the day's movers, and the headlines the analyst agent read.
 */

/** An index name that opens its detail on the statement, the way a scrip does. */
const IndexName = ({ item }) => (
  <Link
    to="/"
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

const Market = () => {
  const navigate = useNavigate();
  // Each feed is shown the moment it arrives; null means still loading.
  const [data, setData] = useState({ indices: null, global: null, trending: null, news: null });

  useEffect(() => {
    const feeds = [
      ['indices', endpoints.marketIndices, (res) => res.data],
      ['global', endpoints.globalIndices, (res) => res.data],
      ['trending', endpoints.trendingStocks, (res) => res.data],
      ['news', endpoints.marketNews, (res) => res.data.articles || []],
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

  const quotes = [...(data.indices || []), ...(data.global || [])];
  const quotesLoading = data.indices === null && data.global === null;
  const done = Object.values(data).every((value) => value !== null);
  if (done && quotes.length === 0 && data.trending.length === 0 && data.news.length === 0) return null;

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
        </Sheet>
      )}

      {data.trending === null && (
        <Sheet title="Movers" meta="NIFTY 50">
          <Ruling rows={4} />
        </Sheet>
      )}
      {data.trending?.length > 0 && (
        <Sheet title="Movers" meta="NIFTY 50">
          <Statement
            columns={[
              { key: 'name', label: 'Scrip' },
              { key: 'value', label: 'Last', align: 'right' },
              { key: 'change', label: 'Change', align: 'right' },
            ]}
          >
            {data.trending.map((item) => (
              <Quote
                key={item.symbol}
                item={item}
                onClick={() => navigate('/research', { state: { symbol: bareSymbol(item.symbol) } })}
              />
            ))}
          </Statement>
        </Sheet>
      )}

      {data.news?.length > 0 && (
        <Sheet title="Headlines" className="lg:col-span-2">
          <ul>
            {data.news.slice(0, 6).map((article, index) => (
              <li key={article.url || index} className="border-b border-[var(--rule)] last:border-b-0">
                <a
                  href={article.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-baseline justify-between gap-4 py-2.5 hover:bg-[var(--paper-sunk)] -mx-2 px-2 transition-colors"
                >
                  <span className="text-sm truncate group-hover:underline decoration-[var(--stamp)] underline-offset-2">
                    {article.title}
                  </span>
                  <span className="doc-meta shrink-0">{formatTimeAgo(article.published_at)}</span>
                </a>
              </li>
            ))}
          </ul>
        </Sheet>
      )}
    </div>
  );
};

export default Market;
