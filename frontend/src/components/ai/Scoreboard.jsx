import React from 'react';
import Card from '../ui/Card';
import Stat from '../ui/Stat';
import Badge from '../ui/Badge';
import Skeleton from '../ui/Skeleton';
import ErrorLine from '../ui/ErrorLine';
import Empty from '../ui/Empty';
import ListRow from '../ui/ListRow';
import { badgeFor } from '../../utils/forward';
import { strategyName } from '../../utils/library';
import { inr } from '../ui/format';
import { toneText } from '../ui/tone';
import { scoreboard } from '../../utils/ai';

const Section = ({ state, children, ...p }) => {
  if (state.error) return <ErrorLine message="Could not load this." onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={p.rows || 3} />;
  return children;
};

/** "4 closed (net +₹120) · 2 open (−₹300)": the total on the right adds open positions at market. */
const strategyLine = (st) => [
  `${st.trades} closed${st.trades ? ` (${inr(st.net, { sign: true })})` : ''}`,
  st.open ? `${st.open} open (${inr(st.unrealized, { sign: true })})` : null,
].filter(Boolean).join(' · ');

/** AI -> Scoreboard: this month, AI vs you vs NIFTY, the book's stats, and each strategy's proven status. */
const Scoreboard = ({ board, card, forward, capital, mineValue }) => {
  const s = scoreboard({ month: board.data?.month, card: card.data, capital, mineValue });
  const strategies = card.data?.strategies || [];
  return (
    <div className="space-y-3">
      <Card title="This month">
        <Section state={board} rows={2}>
          <div className="grid grid-cols-3 gap-3">
            {s.versus.map((v) => <Stat key={v.label} label={v.label} value={<span className={toneText(v.tone)}>{v.value}</span>} />)}
          </div>
          <p className="mt-2 text-[13px] text-[var(--text-muted)]">This month, closed trades net of charges, as % of the money each book works with (AI: its whole book, Picks, engine and news trades, against its capital; you: your holdings). NIFTY is not month-aligned: it is the index since the AI began{s.niftyFrom ? ` (${s.niftyFrom})` : ''}.</p>
        </Section>
      </Card>
      <Card title="Track record">
        <Section state={card} rows={2}>
          {card.data?.totals?.trades === 0 ? (
            <Empty title="No closed trades yet" body="Each closed AI trade lands here, net of charges." />
          ) : (
            <div className="grid grid-cols-2 gap-x-3 gap-y-3">
              {s.stats.map((v) => <Stat key={v.label} label={v.label} value={<span className={toneText(v.tone)}>{v.value}</span>} />)}
            </div>
          )}
        </Section>
      </Card>
      <Card title="Strategies">
        <Section state={card} rows={3}>
          {strategies.length === 0 ? (
            <Empty title="No strategies yet" body="Strategies appear once the AI has a trade." />
          ) : strategies.map((st) => {
            const b = badgeFor(forward, 'engine', st.strategy);
            return (
              <ListRow
                key={st.strategy}
                title={st.strategy === 'unattributed' ? 'Untagged' : strategyName(st.strategy)}
                sub={strategyLine(st)}
                right={<span className="inline-flex items-center gap-2">{b && <Badge kind={b.tone === 'success' ? 'proven' : 'unproven'}>{b.text}</Badge>}{inr(st.total ?? st.net, { sign: true })}</span>}
                rightTone={(st.total ?? st.net) > 0 ? 'gain' : (st.total ?? st.net) < 0 ? 'loss' : 'neutral'}
                chevron={false}
              />
            );
          })}
        </Section>
      </Card>
    </div>
  );
};

export default Scoreboard;
