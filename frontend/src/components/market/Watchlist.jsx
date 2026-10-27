import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import OrderTicket from '../trading/OrderTicket';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import Button from '../ui/Button';
import AsOf from '../ui/AsOf';
import api, { endpoints } from '../../utils/api';
import { stream } from '../../lib/ws';
import { inr, pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { stockPath } from '../../utils/stocks';
import { bareSymbol } from '../../utils/formatters';
import SmartSearch from '../dashboard/SmartSearch';

const Watchlist = () => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);
  const [ticket, setTicket] = useState(null);
  const navigate = useNavigate();

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

  const remove = async (event, symbol) => {
    event.stopPropagation();
    const previous = rows;
    setRows((list) => list.filter((item) => item.symbol !== symbol));
    try {
      await api.delete(endpoints.watchlist.remove(symbol));
    } catch {
      setRows(previous);
    }
  };

  return (
    <Card title="Watchlist">
      {error ? <ErrorLine message="Could not load the watchlist." onRetry={load} />
        : !rows ? <Skeleton rows={4} />
        : rows.length === 0 ? <Empty title="Track a stock" body="Search a name; its page has the Watch toggle." action={<div className="w-full max-w-sm text-left"><SmartSearch compact onSearch={(symbol) => navigate(stockPath(symbol))} /></div>} />
        : rows.map((s) => (
          <div key={s.symbol} className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
            <button type="button" onClick={() => navigate(stockPath(s.symbol))} className="min-w-0 flex-1 min-h-11 text-left active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
              <div className="text-[15px] font-medium text-[var(--text)] truncate">{bareSymbol(s.symbol)}</div>
              <div className="text-[13px] text-[var(--text-muted)] truncate">{s.error ? 'Quote unavailable' : s.name}</div>
            </button>
            <div className="text-right shrink-0">
              <div className="text-[15px] tabular-nums text-[var(--text)]">{inr(s.current_price)}</div>
              <div className={`text-[13px] tabular-nums ${toneText(tone(s.day_change_percent))}`}>
                {s.day_change_percent == null ? '—' : pct(s.day_change_percent / 100, { sign: true })}
              </div>
            </div>
            <Button variant="secondary" className="px-3" onClick={() => setTicket({ symbol: s.symbol, lastPrice: s.current_price })}>Buy</Button>
            <button type="button" onClick={(e) => remove(e, s.symbol)} aria-label={`Remove ${s.symbol} from the watchlist`}
                    className="min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ))}
      {rows?.length > 0 && <AsOf rows={rows} />}
      {ticket && <OrderTicket {...ticket} onClose={() => setTicket(null)} />}
    </Card>
  );
};

export default Watchlist;
