import React from 'react';
import Card from '../ui/Card';
import ListRow from '../ui/ListRow';
import { inr, tone } from '../ui/format';

/**
 * Real-money figures as two labelled rows, never summed: orders placed on the user's own account (`mine`)
 * and the AI account's live autopilot (`ai`). `live` is `{mine, ai}` from `GET /analytics/pnl?venue=live`
 * or the `pnl` socket topic. The AI row is hidden until that account has live trades.
 */
const hasTrades = (book) => !!book && (book.all_time?.trades > 0 || book.open?.positions > 0);

const Line = ({ label, book }) => {
  const today = book.today || {};
  const day = (today.net ?? today.realized ?? 0) + (today.unrealized || 0);
  return (
    <ListRow title={label} sub={`${inr(book.month?.net || 0, { sign: true })} this month · ${book.open?.positions || 0} open`}
             right={inr(day, { sign: true })} rightTone={tone(day)} chevron={false} />
  );
};

const LivePnl = ({ live }) => {
  if (!live || !(hasTrades(live.mine) || hasTrades(live.ai))) return null;
  return (
    <Card title="Live P&L today" action={<span className="text-[13px] text-[var(--text-muted)]">Net of charges</span>}>
      {live.mine && <Line label="Your account" book={live.mine} />}
      {hasTrades(live.ai) && <Line label="AI account" book={live.ai} />}
    </Card>
  );
};

export default LivePnl;
