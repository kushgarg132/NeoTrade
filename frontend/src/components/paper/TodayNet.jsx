import React from 'react';
import { Sheet, Money, NetLine, Ruling } from '../doc/Doc';
import { formatCurrency, formatQuantity } from '../../utils/formatters';

const Line = ({ label, children }) => (
  <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
    <span className="text-[var(--ink-soft)]">{label}</span>
    <span className="figure-md">{children}</span>
  </div>
);

/** Engine → Today: the practice book's day, net of charges. Month and all time live in Book. */
const TodayNet = ({ pnl, loading }) => {
  if (!pnl) {
    return <Sheet title="Today">{loading ? <Ruling rows={3} /> : <p className="text-sm">Couldn’t load today’s figures.</p>}</Sheet>;
  }
  const { today } = pnl;
  const net = (today.net ?? today.realized) + (today.unrealized || 0);
  return (
    <Sheet title="Today" meta="Net of charges">
      <Line label={`Closed trades, after ${formatCurrency(today.costs || 0)} charges`}><Money value={today.net ?? today.realized} /></Line>
      <Line label="Open positions, marked now"><Money value={today.unrealized} /></Line>
      <Line label="Trades closed">
        {formatQuantity(today.trades)}
        {today.trades > 0 && <span className="text-[var(--ink-faint)]"> ({today.wins}W / {today.losses}L)</span>}
      </Line>
      <NetLine label="Net today"><Money value={net} size="lg" /></NetLine>
    </Sheet>
  );
};

export default TodayNet;
