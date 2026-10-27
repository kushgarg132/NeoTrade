import React from 'react';
import { useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Hero from '../components/ui/Hero';
import Stat from '../components/ui/Stat';
import Badge from '../components/ui/Badge';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Empty from '../components/ui/Empty';
import ListRow from '../components/ui/ListRow';
import { useForward } from '../components/ForwardBadge';
import { useAuth } from '../context/AuthContext';
import useStored from '../hooks/useStored';
import { endpoints } from '../utils/api';
import { badgeFor } from '../utils/forward';
import { strategyRow, strategyStatus } from '../utils/aiDetail';
import { aiTradePath } from '../utils/routes';
import { strategyName } from '../utils/library';
import { formatDateTime } from '../utils/formatters';
import { inr, pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';

const BADGE = { Proven: 'proven', Parked: 'neutral', Paused: 'neutral', Unproven: 'unproven' };

/** /ai/strategy/:name: one AI strategy's record, status, backtest and every paper trade. */
const AiStrategy = () => {
  const name = useParams().name;
  const card = useStored(endpoints.analytics.scorecard('paper'));
  const today = useStored(endpoints.today);
  const trades = useStored(endpoints.trades({ strategy: name, venue: 'paper', limit: 200 }));
  const backtest = useStored(endpoints.backtest(name));
  const forward = useForward();
  // Picks are admin-only (routers/picks.py): only an admin's picks:* page asks for the setup's grade.
  const isAdmin = useAuth().user?.role === 'admin';
  const setup = isAdmin && name.startsWith('picks:') ? name.slice(6) : null;
  const picks = useStored(setup ? endpoints.picks.today : null);
  const study = (picks.data?.setups || []).find((s) => s.setup === setup);

  const row = strategyRow(card.data, name);
  const status = strategyStatus({ row, badge: badgeFor(forward, 'engine', name), paused: today.data?.autopilot?.paused, name });
  const bt = backtest.data;

  return (
    <Layout>
      <PageHeader title={strategyName(name)} back="/ai?tab=scoreboard" backLabel="AI"
        right={card.status === 'ok' ? <Badge kind={BADGE[status.label]}>{status.label}</Badge> : null} />
      <div className="space-y-3">
        {!row || card.status !== 'ok' ? (
          <Card title="Paper record">
            {card.status === 'loading' ? <Skeleton rows={2} /> : card.status === 'error' || card.status === 'empty' ? (
              <ErrorLine message="Couldn't load this strategy's record." onRetry={card.retry} />
            ) : <Empty title="No trades yet" body="This strategy's net, open positions and result against NIFTY appear after its first paper trade." />}
          </Card>
        ) : (
          <Hero label="Net · paper" value={row.net} format={(v) => inr(v, { sign: true })}>
            <div className="grid grid-cols-3 gap-3 mt-3">
              <Stat label="Open" value={row.open ? `${row.open} (${inr(row.unrealized, { sign: true })})` : '0'} />
              <Stat label="vs NIFTY" value={row.vs_nifty != null ? <span className={toneText(tone(row.vs_nifty))}>{inr(row.vs_nifty, { sign: true })}</span> : '–'} />
              <Stat label="Win rate" value={row.win_rate != null ? pct(row.win_rate, { dp: 0 }) : '–'} />
            </div>
          </Hero>
        )}

        {setup && picks.status === 'ok' && (
          <Card title="Setup study">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Grade" value={picks.data.grades?.[setup] || '–'} />
              <Stat label="t" value={study?.adjusted?.t != null ? Number(study.adjusted.t).toFixed(2) : '–'} />
            </div>
          </Card>
        )}

        <Card title="Backtest">
          {backtest.status === 'loading' ? <Skeleton rows={2} /> : backtest.status === 'error' ? (
            <ErrorLine message="Couldn't load the backtest." onRetry={backtest.retry} />
          ) : backtest.status === 'empty' ? <Empty title="No backtest recorded" body="The gate's backtest of this strategy appears here once it has run." /> : (
            <>
              <div className="flex items-center gap-2 mb-2">
                <Badge kind={bt.passed ? 'proven' : 'neutral'}>{bt.passed ? 'Passed' : 'Not passed'}</Badge>
                {bt.run_at && <span className="text-[13px] text-[var(--text-muted)]">{formatDateTime(bt.run_at)}</span>}
              </div>
              <div className="grid grid-cols-2 gap-3">
                {bt.total_trades != null && <Stat label="Trades" value={bt.total_trades} />}
                {bt.win_rate != null && <Stat label="Win rate" value={pct(bt.win_rate, { dp: 0 })} />}
                {bt.profit_factor != null && <Stat label="Profit factor" value={Number(bt.profit_factor).toFixed(2)} />}
                {bt.total_pnl != null && <Stat label="Total P&L" value={inr(bt.total_pnl, { sign: true })} />}
                {bt.max_drawdown != null && <Stat label="Max drawdown" value={pct(bt.max_drawdown, { dp: 1 })} />}
                {bt.sharpe_ratio != null && <Stat label="Sharpe ratio" value={Number(bt.sharpe_ratio).toFixed(2)} />}
              </div>
            </>
          )}
        </Card>

        <Card title="Trades">
          {trades.status === 'loading' ? <Skeleton rows={4} /> : trades.status !== 'ok' ? (
            <ErrorLine message="Couldn't load this strategy's trades." onRetry={trades.retry} />
          ) : trades.data.length === 0 ? <Empty title="No trades yet" body="Each paper trade this strategy places is listed here." /> : trades.data.map((t) => (
            <ListRow
              key={t.id}
              to={aiTradePath(t.id)}
              dense
              title={`${t.symbol} · ${t.side}`}
              sub={`${formatDateTime(t.entry_at)}${t.status === 'OPEN' ? ' · open' : ''}`}
              right={t.status === 'OPEN' ? 'Open' : inr((t.realized_pnl || 0) - (t.costs || 0), { sign: true })}
              rightTone={t.status === 'OPEN' ? 'neutral' : tone((t.realized_pnl || 0) - (t.costs || 0))}
            />
          ))}
        </Card>
      </div>
    </Layout>
  );
};

export default AiStrategy;
