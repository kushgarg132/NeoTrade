import React, { useCallback, useEffect, useState } from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import ListRow from '../ui/ListRow';
import { Link } from 'react-router-dom';
import Badge from '../ui/Badge';
import { inr, pct } from '../ui/format';
import { stockPath } from '../../utils/stocks';
import { aiTradePath } from '../../utils/routes';
import api, { endpoints } from '../../utils/api';
import { closedTrades, openTradeIds } from '../../utils/aiDetail';
import { Segmented } from '../settings/Fields';
import { useLoad } from '../ideas/useLoad';
import { px } from '../ideas/levels';

/** Open: what the AI holds now, each row opens its trade (else the stock). */
const OpenPositions = ({ state }) => {
  const [ids, setIds] = useState({});
  const symbols = Object.keys(state.data || {}).sort().join(',');
  // Positions carry no trade id: map symbol -> open trade once. A failed fetch just leaves rows linking to the stock.
  useEffect(() => {
    let live = true;
    api.get(endpoints.trades({ status: 'OPEN', venue: 'paper' })).then((r) => live && setIds(openTradeIds(r.data))).catch(() => {});
    return () => { live = false; };
  }, [symbols]);
  if (state.error) return <ErrorLine message="Couldn't load the AI's positions." onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={4} />;
  const rows = Object.values(state.data || {}).filter((p) => p.quantity);
  const total = rows.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);
  if (rows.length === 0) return <Empty title="Nothing open" body="Positions the AI holds appear here once it places a trade."
    action={<Link to="/settings/autopilot" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold">Check autopilot in Settings</Link>} />;
  return (
    <Card title={<span className="inline-flex items-center gap-2">{rows.length} open <Badge kind="paper">Paper</Badge></span>} action={<span className={`private text-[15px] font-semibold tabular-nums ${total < 0 ? 'text-[var(--loss)]' : 'text-[var(--gain)]'}`}>{inr(total, { sign: true })}</span>}>
      {rows.map((p) => (
        <ListRow
          key={p.symbol}
          to={ids[p.symbol] != null ? aiTradePath(ids[p.symbol]) : stockPath(p.symbol)}
          title={p.symbol}
          dense
          sub={<>{p.quantity} @ <span className="private">{px(p.avg_price)}</span></>}
          right={`${inr(p.unrealized_pnl, { sign: true })} (${pct(p.unrealized_pnl / (p.quantity * p.avg_price || 1), { sign: true })})`}
          rightTone={p.unrealized_pnl > 0 ? 'gain' : p.unrealized_pnl < 0 ? 'loss' : 'neutral'}
        />
      ))}
    </Card>
  );
};

const day = (d) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' });
const held = (a, b) => Math.max(0, Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000));

/** Closed: the AI's finished paper trades, newest first, with net P&L after charges; each opens its trade. */
const ClosedPositions = () => {
  const state = useLoad(useCallback(() => api.get(endpoints.trades({ status: 'CLOSED', venue: 'paper' })).then((r) => r.data), []));
  if (state.loading) return <Skeleton rows={4} />;
  if (state.error) return <ErrorLine message="Couldn't load the AI's closed trades." onRetry={state.reload} />;
  const { rows, total, wins } = closedTrades(state.data);
  if (!rows.length) return <Empty title="Nothing closed yet" body="Trades the AI has exited show here with their profit or loss after charges." />;
  return (
    <Card title={<span className="inline-flex items-center gap-2">{rows.length} closed <Badge kind="paper">Paper</Badge></span>}
          action={<span className={`private text-[15px] font-semibold tabular-nums ${total < 0 ? 'text-[var(--loss)]' : 'text-[var(--gain)]'}`}>{inr(total, { sign: true })}</span>}>
      <p className="-mt-1 mb-1 text-[13px] text-[var(--text-muted)]">{wins} of {rows.length} made money · net of charges</p>
      {rows.map((t) => (
        <ListRow
          key={t.id}
          to={aiTradePath(t.id)}
          title={t.symbol}
          dense
          sub={<>{t.quantity} · <span className="private">{px(t.entry_price)} → {px(t.exit_price)}</span> · {t.exit_at ? `${day(t.exit_at)}, ${held(t.entry_at, t.exit_at)}d held` : ''}</>}
          right={`${inr(t.net, { sign: true })}${t.ret != null ? ` (${pct(t.ret, { sign: true })})` : ''}`}
          rightTone={t.net > 0 ? 'gain' : t.net < 0 ? 'loss' : 'neutral'}
        />
      ))}
    </Card>
  );
};

/** AI -> Positions: Open (held now) or Closed (finished trades with their P&L). */
const Positions = ({ state }) => {
  const [view, setView] = useState('open');
  return (
    <div className="space-y-3">
      <Segmented label="Positions" options={[['open', 'Open'], ['closed', 'Closed']]} value={view} onChange={setView} />
      {view === 'open' ? <OpenPositions state={state} /> : <ClosedPositions />}
    </div>
  );
};

export default Positions;
