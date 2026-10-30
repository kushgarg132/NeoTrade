import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { X } from 'lucide-react';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import AsOf from '../ui/AsOf';
import api, { endpoints } from '../../utils/api';
import { stream } from '../../lib/ws';
import { inr, pct, points, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { stockPath } from '../../utils/stocks';
import { bareSymbol } from '../../utils/formatters';
import { companyName, rangeAt } from '../../utils/market';
import SmartSearch from '../dashboard/SmartSearch';
import { px } from '../ideas/levels';
import NewsChip from '../common/NewsChip';
import useSymbolNews from '../../hooks/useSymbolNews';

const Panel = ({ children, className = '' }) => (
  <section className={`rounded-[20px] border border-[var(--border)] bg-[var(--surface)] ${className}`}>{children}</section>
);

/** Today's price inside its 52-week low..high, as a dot on a line with both ends priced. */
const Range52 = ({ s, money }) => {
  const at = rangeAt(s.current_price, s.low_52w, s.high_52w);
  if (at == null) return null;
  return (
    <div className="mt-2.5 flex items-center gap-2 sm:max-w-md text-[12px] tabular-nums text-[var(--text-muted)]"
      role="img" aria-label={`52-week range ${money(s.low_52w)} to ${money(s.high_52w)}, now ${Math.round(at * 100)}% of the way up`}>
      <span className="shrink-0">52w {money(s.low_52w)}</span>
      <div className="relative h-1 flex-1 rounded-full bg-[var(--surface-2)]">
        <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--surface)] bg-[var(--text)]" style={{ left: `${at * 100}%` }} />
      </div>
      <span className="shrink-0">{money(s.high_52w)}</span>
    </div>
  );
};

/** One watched stock: symbol and company, price and day move, where it sits in its year, its latest news. */
const Row = ({ s, entry, editing, onRemove }) => {
  const money = s.currency && s.currency !== 'INR' ? points : inr; // range ends: whole rupees
  const price = s.currency && s.currency !== 'INR' ? points : px;  // the quote: to the paisa
  const name = companyName(s.name, s.symbol);
  const move = s.day_change_percent;
  return (
    <li className="flex items-start gap-2 px-4 py-3.5 border-b border-[var(--border)] last:border-b-0">
      <div className="min-w-0 flex-1">
        <Link to={stockPath(s.symbol)} className="tap -mx-2 block rounded-[12px] px-2 py-1 hover:bg-[var(--surface-2)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">{bareSymbol(s.symbol)}</span>
            <span className="shrink-0 text-[17px] font-semibold tabular-nums text-[var(--text)]">{s.error ? '—' : price(s.current_price)}</span>
          </div>
          <div className="mt-0.5 flex items-center justify-between gap-3">
            <span className="min-w-0 truncate text-[13px] text-[var(--text-muted)]">{s.error ? 'Quote unavailable' : name}</span>
            {move != null && (
              <span className={`shrink-0 inline-flex items-center gap-0.5 rounded-full px-2 min-h-6 text-[13px] font-semibold tabular-nums ${toneText(tone(move))}`}
                style={{ background: `var(${move > 0 ? '--gain-soft' : move < 0 ? '--loss-soft' : '--surface-2'})` }}>
                {move > 0 ? '▲' : move < 0 ? '▼' : ''} {pct(Math.abs(move) / 100)}
              </span>
            )}
          </div>
          {!s.error && <Range52 s={s} money={money} />}
        </Link>
        {entry?.headline && <NewsChip entry={entry} className="mt-2 max-w-none" />}
      </div>
      {editing && (
        <button type="button" onClick={(e) => onRemove(e, s.symbol)} aria-label={`Remove ${bareSymbol(s.symbol)} from the watchlist`}
          className="tap mt-0.5 -mr-1 inline-flex w-11 h-11 shrink-0 items-center justify-center rounded-[12px] bg-[var(--loss-soft)] text-[var(--loss)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
          <X className="w-5 h-5" aria-hidden="true" />
        </button>
      )}
    </li>
  );
};

/** Market → Watchlist: add from the search on top, each watched stock as a quiet quote row (live prices over the
 * socket), Edit to remove. Buying happens on the stock page. */
const Watchlist = () => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [addError, setAddError] = useState(null);
  const { news } = useSymbolNews((rows || []).map((r) => r.symbol));

  const [tick, setTick] = useState(0);
  useEffect(() => {
    api.get(endpoints.watchlist.details).then((res) => setRows(res.data)).catch(() => setError(true));
  }, [tick]);
  const load = () => { setError(false); setTick((t) => t + 1); };

  // The server's price pump polls exactly the symbols subscribed here (~15s).
  const symbolsKey = (rows || []).filter((r) => !r.error).map((r) => r.symbol).join(',');
  useEffect(() => {
    const offs = symbolsKey.split(',').filter(Boolean).map((symbol) =>
      stream.subscribe(`prices:${symbol.toUpperCase().replace(/\.NS$/, '')}`, ({ data }) => {
        if (!(data?.price > 0)) return;
        setRows((list) => list.map((r) => {
          if (r.symbol !== symbol) return r;
          const prev = r.previous_close;
          const at = Date.now() / 1000;
          return prev
            ? { ...r, current_price: data.price, day_change: data.price - prev, day_change_percent: (data.price / prev - 1) * 100, at }
            : { ...r, current_price: data.price, at };
        }));
      }));
    return () => offs.forEach((off) => off());
  }, [symbolsKey]);

  const add = (symbol) => {
    setAddError(null);
    if ((rows || []).some((r) => bareSymbol(r.symbol).toUpperCase() === bareSymbol(symbol).toUpperCase())) return;
    api.post(endpoints.watchlist.add(symbol)).then(load)
      .catch((err) => setAddError(err?.response?.data?.detail || `Could not add ${bareSymbol(symbol)}.`));
  };

  const remove = async (event, symbol) => {
    event.stopPropagation();
    const at = rows.findIndex((item) => item.symbol === symbol);
    const gone = rows[at];
    setRows((list) => list.filter((item) => item.symbol !== symbol));
    try {
      await api.delete(endpoints.watchlist.remove(symbol));
    } catch {
      // Put back only this row: another removal may have succeeded meanwhile.
      setRows((list) => (list.some((item) => item.symbol === symbol) ? list : [...list.slice(0, at), gone, ...list.slice(at)]));
    }
  };

  if (error) return <Panel className="p-4"><ErrorLine message="Could not load the watchlist." onRetry={load} /></Panel>;
  if (!rows) return <Panel className="p-4"><Skeleton rows={4} /></Panel>;
  if (rows.length === 0) {
    return (
      <Panel className="p-4">
        <Empty title="Track a stock" body="Search a company or symbol to watch its price, its 52-week range and its news." action={<div className="w-full max-w-sm text-left"><SmartSearch compact onSearch={add} /></div>} />
        {addError && <p role="alert" className="mt-2 text-center text-[14px] text-[var(--loss)]">{addError}</p>}
      </Panel>
    );
  }
  return (
    <div className="space-y-3">
      <div>
        <SmartSearch compact onSearch={add} />
        {addError && <p role="alert" className="mt-1.5 text-[14px] text-[var(--loss)]">{addError}</p>}
      </div>
      <div className="flex items-center justify-between px-1">
        <h2 className="text-[15px] font-semibold text-[var(--text)]">Watching <span className="font-medium tabular-nums text-[var(--text-muted)]">{rows.length}</span></h2>
        <button type="button" aria-pressed={editing} onClick={() => setEditing((v) => !v)}
          className="tap min-h-11 rounded-[12px] px-3 text-[14px] font-semibold text-[var(--accent)] hover:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
          {editing ? 'Done' : 'Edit'}
        </button>
      </div>
      <Panel>
        <ul>{rows.map((s) => <Row key={s.symbol} s={s} entry={news[s.symbol?.toUpperCase().replace(/\.NS$/, '')]} editing={editing} onRemove={remove} />)}</ul>
      </Panel>
      <div className="px-1"><AsOf rows={rows} /></div>
    </div>
  );
};

export default Watchlist;
