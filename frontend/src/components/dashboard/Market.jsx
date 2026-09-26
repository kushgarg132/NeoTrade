import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sheet, Statement, Row, Cell, Ruling } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { formatSignedPercent, formatNoteDate, formatTimeAgo } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * Market context, printed as one appendix rather than four competing widgets:
 * the indices, the day's movers, and the headlines the analyst agent read.
 */

const Quote = ({ item, onClick }) => (
  <Row className={onClick && 'cursor-pointer hover:bg-[var(--paper-sunk)]'} onClick={onClick}>
    <Cell>
      <span className="text-sm">{item.name || item.symbol}</span>
    </Cell>
    <Cell align="right" mono>
      {typeof item.value === 'number' ? item.value.toFixed(2) : '—'}
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
  const [data, setData] = useState({ indices: [], global: [], trending: [], news: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      api.get(endpoints.marketIndices),
      api.get(endpoints.globalIndices),
      api.get(endpoints.trendingStocks),
      api.get(endpoints.marketNews),
    ])
      .then(([indices, global, trending, news]) => {
        setData({
          indices: indices.status === 'fulfilled' ? indices.value.data : [],
          global: global.status === 'fulfilled' ? global.value.data : [],
          trending: trending.status === 'fulfilled' ? trending.value.data : [],
          news: news.status === 'fulfilled' ? news.value.data.articles || [] : [],
        });
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Sheet title="Market">
        <Ruling rows={4} />
      </Sheet>
    );
  }

  const quotes = [...data.indices, ...data.global];
  if (quotes.length === 0 && data.trending.length === 0 && data.news.length === 0) return null;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
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
              <Quote key={item.symbol || item.name} item={item} />
            ))}
          </Statement>
        </Sheet>
      )}

      {data.trending.length > 0 && (
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
                onClick={() => navigate('/', { state: { symbol: item.symbol } })}
              />
            ))}
          </Statement>
        </Sheet>
      )}

      {data.news.length > 0 && (
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
