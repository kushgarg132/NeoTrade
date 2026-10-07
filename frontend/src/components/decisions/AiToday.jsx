import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Empty, Ruling } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { cn } from '../../utils/cn';
import { formatClock } from '../../utils/formatters';

/**
 * What the AI account's autopilot did today, read only. The autopilot
 * decides for itself inside its fence; this page only reports it.
 */
const istDay = (value) => new Date(value).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

const AiToday = () => {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    api
      .get(endpoints.settings.autopilotLog)
      .then((res) => {
        const today = istDay(Date.now());
        setRows((res.data.rows || []).filter((row) => row.at && istDay(row.at) === today).slice(0, 10));
      })
      .catch(() => setRows([]));
  }, []);

  return (
    <Sheet
      title="AI account today"
      actions={
        <Link to="/ai/activity" className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">
          See all on AI → Activity ›
        </Link>
      }
    >
      {rows === null ? (
        <Ruling rows={3} />
      ) : rows.length === 0 ? (
        <Empty title="The autopilot has not acted today." />
      ) : (
        <ul className="divide-y divide-[var(--rule)]">
          {rows.map((row, i) => (
            <li key={`${row.at}-${i}`} className="py-2 flex items-baseline gap-3 text-sm">
              <span className="doc-meta shrink-0">
                {formatClock(row.at)}
              </span>
              <span className={cn('flex-1 min-w-0 truncate', !['FILLED', 'SENT'].includes(row.status) && 'text-[var(--ink-soft)]')}>
                {row.status === 'FILLED'
                  ? row.side === 'SELL' ? 'Sold' : 'Bought'
                  : row.status === 'SENT'
                    ? `Sent ${row.side === 'SELL' ? 'sell' : 'buy'}`
                    : `Refused ${row.side?.toLowerCase() || ''}`}{' '}
                {row.quantity} {row.symbol}
                {row.status === 'SENT' ? ' · with the broker, not filled yet' : ''}
                {row.status !== 'FILLED' && row.status !== 'SENT' && row.reason ? ` · ${row.reason}` : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
};

export default AiToday;
