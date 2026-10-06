import React, { useEffect, useState } from 'react';
import { Sheet, Scrip, Ruling } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { useReconnect, useTopic } from '../../hooks/useStream';
import { formatClock, formatCurrency, formatQuantity } from '../../utils/formatters';
import { cn } from '../../utils/cn';

const istDay = (value) => new Date(new Date(value).getTime() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);
const SHOWN = 10;

/** Engine → Traded today: the practice book's fills since midnight IST, newest first. */
const TradedToday = () => {
  const [fills, setFills] = useState(null);
  const [failed, setFailed] = useState(false);
  const [all, setAll] = useState(false);

  const load = () =>
    api.get(endpoints.trading.fills('paper'))
      .then((res) => {
        const today = istDay(Date.now());
        setFills(res.data.filter((f) => istDay(f.timestamp) === today)
          .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)));
        setFailed(false);
      })
      .catch(() => setFailed(true));
  useEffect(() => {
    load();
  }, []);
  useTopic('trades', load);
  useReconnect(load);

  const shown = all ? fills : fills?.slice(0, SHOWN);
  return (
    <Sheet title="Traded today" meta={fills ? `${fills.length} fill${fills.length === 1 ? '' : 's'}` : undefined}>
      {failed ? <p className="text-sm">Couldn’t load today’s fills.</p> : fills === null ? <Ruling rows={3} /> : fills.length === 0 ? (
        <p className="doc-meta normal-case">No fills today.</p>
      ) : (
        <>
          <ul className="divide-y divide-[var(--rule)]">
            {shown.map((f) => (
              <li key={`${f.order_id}-${f.timestamp}`} className="py-2 flex items-baseline gap-2 text-sm">
                <Scrip symbol={f.symbol} />
                <span className={cn('field-label', f.side === 'BUY' ? 'text-up' : 'text-down')}>{f.side}</span>
                <span className="doc-meta">{formatClock(f.timestamp)}</span>
                <span className="ml-auto figure-md">{formatQuantity(f.quantity)} @ {formatCurrency(f.price)}</span>
              </li>
            ))}
          </ul>
          {fills.length > SHOWN && (
            <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all}
                    className="mt-1 field-label text-[var(--stamp)] hover:underline min-h-11 sm:min-h-0">
              {all ? `Show latest ${SHOWN}` : `Show all ${fills.length}`}
            </button>
          )}
        </>
      )}
    </Sheet>
  );
};

export default TradedToday;
