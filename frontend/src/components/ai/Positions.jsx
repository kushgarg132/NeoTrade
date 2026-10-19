import React from 'react';
import Card from '../ui/Card';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import ListRow from '../ui/ListRow';
import { inr } from '../ui/format';
import { stockPath } from '../../utils/stocks';

/** AI -> Positions: what the AI holds now, each row opens the stock. */
const Positions = ({ state }) => {
  if (state.error) return <ErrorLine message="Could not load the AI book." onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={4} />;
  const rows = Object.values(state.data || {}).filter((p) => p.quantity);
  const total = rows.reduce((sum, p) => sum + (p.unrealized_pnl || 0), 0);
  if (rows.length === 0) return <Empty title="Nothing open" body="Positions the AI holds appear here." />;
  return (
    <Card title={`${rows.length} open`} action={<span className={`private text-[15px] font-semibold tabular-nums ${total < 0 ? 'text-[var(--loss)]' : 'text-[var(--gain)]'}`}>{inr(total, { sign: true })}</span>}>
      {rows.map((p) => (
        <ListRow
          key={p.symbol}
          to={stockPath(p.symbol)}
          title={p.symbol}
          sub={`${p.quantity} @ ${inr(p.avg_price)}`}
          right={inr(p.unrealized_pnl, { sign: true })}
          rightTone={p.unrealized_pnl > 0 ? 'gain' : p.unrealized_pnl < 0 ? 'loss' : 'neutral'}
        />
      ))}
    </Card>
  );
};

export default Positions;
