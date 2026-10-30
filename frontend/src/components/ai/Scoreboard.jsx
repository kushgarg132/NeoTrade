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

// Track-record labels short enough for a phone's three columns.
const SHORT = { 'Max drawdown (peak to trough)': 'Max drawdown', 'vs same money in NIFTY': 'vs NIFTY' };

/** AI, You and NIFTY this month as bars from a zero line on one scale, the figure beside each. */
const Versus = ({ rows }) => {
  const max = Math.max(0.5, ...rows.map((r) => Math.abs(r.pct ?? 0)));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[3.5rem_minmax(0,1fr)_4rem] items-center gap-3">
          <span className="text-[14px] font-semibold text-[var(--text)]">{r.label}</span>
          <span className="relative h-2.5 rounded-full bg-[var(--surface-2)]" aria-hidden="true">
            <span className="absolute inset-y-[-3px] left-1/2 w-px bg-[var(--border)]" />
            {r.pct ? <span className={`absolute inset-y-0 rounded-full ${r.pct > 0 ? 'left-1/2 bg-[var(--gain)]' : 'right-1/2 bg-[var(--loss)]'}`} style={{ width: `${(Math.abs(r.pct) / max) * 50}%` }} /> : null}
          </span>
          <span className={`text-right text-[15px] font-semibold tabular-nums ${toneText(r.tone)}`}>{r.value}</span>
        </li>
      ))}
    </ul>
  );
};
const settingsLink = (label) => <Link to="/settings/autopilot" className="inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold">{label}</Link>;
const Section = ({ state, children, what, ...p }) => {
  if (state.error) return <ErrorLine message={`Couldn't load the AI's ${what}.`} onRetry={state.retry} />;
  if (!state.loaded) return <Skeleton rows={p.rows || 3} />;
  return children;
};

/** "4 closed (net +₹120) · 2 open (−₹300) · vs NIFTY −₹80": the total on the right adds open positions at market. */
const amount = (n) => <span className="private">{inr(n, { sign: true })}</span>;
const strategyLine = (st) => [
  <>{st.trades} closed{st.trades ? <> ({amount(st.net)})</> : ''}</>,
  st.open ? <>{st.open} open ({amount(st.unrealized)})</> : null,
  st.vs_nifty != null ? <>vs NIFTY {amount(st.vs_nifty)}</> : null,
].filter(Boolean).flatMap((x, i) => (i ? [' · ', x] : [x])).map((x, i) => <React.Fragment key={i}>{x}</React.Fragment>);

/** AI -> Scoreboard: this month, AI vs you vs NIFTY, the book's stats, and each strategy's proven status. */
const Scoreboard = ({ board, card, forward, capital, mineValue }) => {
  const s = scoreboard({ month: board.data?.month, card: card.data, capital, mineValue });
  const strategies = card.data?.strategies || [];
  return (
    <div className="space-y-3">
      <Card title="This month">
        <Section state={board} rows={2} what="monthly score">
          <Versus rows={s.versus} />
          <p className="mt-3 text-[12px] text-[var(--text-muted)]">Closed trades after charges, as % of each book's capital. NIFTY is since the AI began{s.niftyFrom ? ` (${s.niftyFrom})` : ''}.</p>
        </Section>
      </Card>
      <Card title="Track record">
        <Section state={card} rows={2} what="track record">
          {card.data?.totals?.trades === 0 ? (
            <Empty title="No closed trades yet" body="Each closed AI trade lands here, after charges. It starts once the autopilot places a trade." action={settingsLink('Check autopilot settings')} />
          ) : (
            <div className="grid grid-cols-3 gap-x-3 gap-y-3 sm:grid-cols-5">
              {s.stats.map((v) => <Stat key={v.label} label={SHORT[v.label] || v.label} value={<span className={toneText(v.tone)}>{v.value}</span>} />)}
            </div>
          )}
        </Section>
      </Card>
      <Card title="Strategies">
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
