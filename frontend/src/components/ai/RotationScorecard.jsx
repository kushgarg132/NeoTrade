import React from 'react';
import Card from '../ui/Card';
import Stat from '../ui/Stat';
import Badge from '../ui/Badge';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import useStored from '../../hooks/useStored';
import { endpoints } from '../../utils/api';
import { gateLine, pct, versusRows, vetoLine } from '../../utils/plan';
import { Versus } from './Scoreboard';

/** AI > Scoreboard: the weekly rotation's paper record vs NIFTY and the Momentum 30 ETF (GET /plan/scorecard),
    the live gate and how the news vetoes did. Nothing before the first daily plan. */
const RotationScorecard = () => {
  const { data, status, retry } = useStored(endpoints.planScorecard);
  if (status === 'loading') return <Card title="Rotation record"><Skeleton rows={3} /></Card>;
  if (status === 'error') return <Card title="Rotation record"><ErrorLine message="Couldn't load the rotation record." onRetry={retry} /></Card>;
  const card = data?.scorecard;
  if (!card) return null;
  const veto = vetoLine(card.vetoes);
  return (
    <Card title="Rotation record" action={<Badge kind={card.live_ready ? 'proven' : 'paper'}>{card.live_ready ? 'Live gate met' : 'Paper'}</Badge>}>
      <p className="mb-3 text-[13px] text-[var(--text-muted)]">Since {card.since} · {card.days} days</p>
      <Versus rows={versusRows(card)} />
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Stat label="Max drawdown" value={pct(card.max_drawdown)} tone={card.max_drawdown < 0 ? 'loss' : 'neutral'} />
        <Stat label="Live from" value={card.unlock_on} />
      </div>
      <p className={`mt-3 text-[14px] ${card.ahead ? 'text-[var(--text)]' : 'text-[var(--warn)]'}`}>{gateLine(card)}</p>
      {veto && <p className="mt-2 text-[13px] text-[var(--text-muted)]">{veto}</p>}
    </Card>
  );
};

export default RotationScorecard;
