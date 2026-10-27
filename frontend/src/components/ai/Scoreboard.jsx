import React from 'react';
import { Link } from 'react-router-dom';
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
import { strategyPath } from '../../utils/routes';

const Paper = () => <Badge kind="paper">Paper</Badge>;
const settingsLink = (label) => <Link to="/settings/autopilot" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold">{label}</Link>;
const Section = ({ state, children, what, ...p }) => {
  if (state.error) return <ErrorLine message={`Couldn't load the AI's ${what}.`} onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={p.rows || 3} />;
  return children;
};

/** "4 closed (net +₹120) · 2 open (−₹300) · vs NIFTY −₹80": the total on the right adds open positions at market. */
const strategyLine = (st) => [
  `${st.trades} closed${st.trades ? ` (${inr(st.net, { sign: true })})` : ''}`,
  st.open ? `${st.open} open (${inr(st.unrealized, { sign: true })})` : null,
  st.vs_nifty != null ? `vs NIFTY ${inr(st.vs_nifty, { sign: true })}` : null,
].filter(Boolean).join(' · ');

/** AI -> Scoreboard: this month, AI vs you vs NIFTY, the book's stats, and each strategy's proven status. */
const Scoreboard = ({ board, card, forward, capital, mineValue }) => {
  const s = scoreboard({ month: board.data?.month, card: card.data, capital, mineValue });
  const strategies = card.data?.strategies || [];
  return (
    <div className="space-y-3">
      <Card title="This month" action={<Paper />}>
        <Section state={board} rows={2} what="monthly score">
          <div className="grid grid-cols-3 gap-3">
            {s.versus.map((v) => <Stat key={v.label} label={v.label} value={<span className={toneText(v.tone)}>{v.value}</span>} />)}
          </div>
          <p className="mt-2 text-[13px] text-[var(--text-muted)]">Closed trades this month, after charges, as % of each book's capital. You = your own account. NIFTY is the index since the AI began{s.niftyFrom ? ` (${s.niftyFrom})` : ''}, not this month.</p>
        </Section>
      </Card>
      <Card title="Track record" action={<Paper />}>
        <Section state={card} rows={2} what="track record">
          {card.data?.totals?.trades === 0 ? (
            <Empty title="No closed trades yet" body="Each closed AI trade lands here, after charges. It starts once the autopilot places a trade." action={settingsLink('Check autopilot settings')} />
          ) : (
            <div className="grid grid-cols-2 gap-x-3 gap-y-3">
              {s.stats.map((v) => <Stat key={v.label} label={v.label} value={<span className={toneText(v.tone)}>{v.value}</span>} />)}
            </div>
          )}
        </Section>
      </Card>
      <Card title="Strategies" action={<Paper />}>
        <Section state={card} rows={3} what="strategies">
          {strategies.length === 0 ? (
            <Empty title="No strategies yet" body="Each strategy the AI trades gets a line here with its proven status." action={settingsLink('Check autopilot settings')} />
          ) : strategies.map((st) => {
            const b = badgeFor(forward, 'engine', st.strategy);
            return (
              <ListRow
                key={st.strategy}
                title={st.strategy === 'unattributed' ? 'Untagged' : strategyName(st.strategy)}
                sub={strategyLine(st)}
                right={<span className="inline-flex items-center gap-2">{b && <Badge kind={b.tone === 'success' ? 'proven' : 'unproven'}>{b.text}</Badge>}{inr(st.total ?? st.net, { sign: true })}</span>}
                rightTone={(st.total ?? st.net) > 0 ? 'gain' : (st.total ?? st.net) < 0 ? 'loss' : 'neutral'}
                to={st.strategy === 'unattributed' ? undefined : strategyPath(st.strategy)}
                dense
              />
            );
          })}
        </Section>
      </Card>
    </div>
  );
};

export default Scoreboard;
