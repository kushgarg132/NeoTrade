import React, { useEffect, useState } from 'react';
import { Sheet, Money } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { monthLabel } from '../../utils/months';

const pct = (x) => `${x >= 0 ? '+' : '−'}${Math.abs(x * 100).toFixed(1)}%`;

/** The AI account against the user's own, month by month, after charges. */
const AiVsMeSheet = () => {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api.get(endpoints.journal.aiVsMe).then((res) => setRows(res.data)).catch(() => setRows([]));
  }, []);
  // From the first month the AI account traded: before it, every AI cell is ₹0.
  const first = (rows || []).findIndex((r) => r.ai.fills > 0);
  if (first < 0) return null;
  const ret = (x) => (x === null || x === undefined ? '—' : pct(x));
  return (
    <Sheet title="AI vs you" meta="Net of estimated charges">
      <ul className="divide-y divide-[var(--rule)]">
        {rows.slice(first).slice(-6).reverse().map((r) => (
          <li key={r.month} className="py-2 grid grid-cols-4 gap-2 items-baseline text-sm">
            <span className="field-label">{monthLabel(r.month, 'short')}</span>
            <span><span className="doc-meta">AI </span><Money value={r.ai.net_pnl} size="sm" /></span>
            <span><span className="doc-meta">You </span><Money value={r.mine.net_pnl} size="sm" /></span>
            <span className="figure-md text-right">Nifty {ret(r.nifty_return)}</span>
          </li>
        ))}
      </ul>
    </Sheet>
  );
};

export default AiVsMeSheet;
