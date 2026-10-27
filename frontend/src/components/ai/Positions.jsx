import React, { useEffect, useState } from 'react';
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
import { openTradeIds } from '../../utils/aiDetail';

/** AI -> Positions: what the AI holds now, each row opens the stock. */
const Positions = ({ state }) => {
  const [ids, setIds] = useState({});
  // Positions carry no trade id: map symbol -> open trade once. A failed fetch just leaves rows linking to the stock.
  useEffect(() => {
    let live = true;
    api.get(endpoints.trades({ status: 'OPEN', venue: 'paper' })).then((r) => live && setIds(openTradeIds(r.data))).catch(() => {});
    return () => { live = false; };
  }, [state.data]);
  if (state.error) return <ErrorLine message="Couldn't load the AI's positions." onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={4} />;
  const rows = Object.values(state.data || {}).filter((p) => p.quantity);
  const total = rows.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);
  if (rows.length === 0) return <Empty title="Nothing open" body="Positions the AI holds appear here once it places a trade."
    action={<Link to="/settings?tab=limits" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--surface)] text-[15px] font-semibold">Check autopilot in Limits</Link>} />;
  return (
    <Card title={<span className="inline-flex items-center gap-2">{rows.length} open <Badge kind="paper">Paper</Badge></span>} action={<span className={`private text-[15px] font-semibold tabular-nums ${total < 0 ? 'text-[var(--loss)]' : 'text-[var(--gain)]'}`}>{inr(total, { sign: true })}</span>}>
      {rows.map((p) => (
        <ListRow
          key={p.symbol}
          to={ids[p.symbol] != null ? aiTradePath(ids[p.symbol]) : stockPath(p.symbol)}
          title={p.symbol}
          dense
          sub={`${p.quantity} @ ${inr(p.avg_price)}`}
          right={`${inr(p.unrealized_pnl, { sign: true })} (${pct(p.unrealized_pnl / (p.quantity * p.avg_price || 1), { sign: true })})`}
          rightTone={p.unrealized_pnl > 0 ? 'gain' : p.unrealized_pnl < 0 ? 'loss' : 'neutral'}
        />
      ))}
    </Card>
  );
};

export default Positions;
