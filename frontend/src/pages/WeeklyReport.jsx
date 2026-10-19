import React, { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Stat from '../components/ui/Stat';
import ListRow from '../components/ui/ListRow';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import { useLoad } from '../components/ideas/useLoad';
import api, { endpoints } from '../utils/api';
import { bareSymbol } from '../utils/formatters';
import { inr, pct, tone } from '../components/ui/format';
import { shiftWeek, weekRange } from '../utils/weekly';

const navCls = 'inline-flex items-center justify-center min-h-11 min-w-11 text-[var(--text-muted)] disabled:opacity-40';

/** Last week for the user's own account; the same numbers Telegram sends on Sunday 18:00. */
const WeeklyReport = () => {
  const [params, setParams] = useSearchParams();
  const week = params.get('week');
  const { data: r, loading, error, reload } = useLoad(useCallback(
    () => api.get(endpoints.weeklyReport(week)).then((x) => x.data), [week]));
  const go = (by) => setParams({ week: shiftWeek(r?.week || week, by) });
  const shown = r?.week || week;

  return (
    <Layout>
      <PageHeader title="Weekly report" back="/" />
      <div className="flex items-center justify-between mb-3">
        <button type="button" aria-label="Previous week" className={navCls} disabled={!shown} onClick={() => go(-1)}>
          <ChevronLeft className="w-5 h-5" />
        </button>
        <div className="text-center">
          <div className="text-[15px] font-semibold text-[var(--text)]">{shown || '…'}</div>
          {shown && <div className="text-[13px] text-[var(--text-muted)]">{weekRange(shown)}</div>}
        </div>
        <button type="button" aria-label="Next week" className={navCls} disabled={!shown} onClick={() => go(1)}>
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>
      {loading ? <Skeleton rows={6} />
        : error ? <ErrorLine message="Could not load this week." onRetry={reload} />
        : (
          <div className="space-y-4">
            <Card title="You against NIFTY">
              {r.you.ret == null ? <Empty title="No curve for this week" body="Import trades or connect a broker to see it." /> : (
                <div className="grid grid-cols-3 gap-3">
                  <Stat label="You" value={pct(r.you.ret, { sign: true })} tone={tone(r.you.ret)} />
                  <Stat label="NIFTY" value={pct(r.you.nifty, { sign: true })} tone={tone(r.you.nifty)} />
                  <Stat label="Excess" value={pct(r.you.excess, { sign: true })} tone={tone(r.you.excess)} />
                </div>
              )}
              <div className="mt-3 pt-3 border-t border-[var(--border)]">
                <Stat label="AI book" value={pct(r.ai.ret, { sign: true })} tone={tone(r.ai.ret)} />
              </div>
            </Card>
            <Card title="Best and worst">
              {r.best.length + r.worst.length === 0 ? <Empty title="No closed trades" body="Nothing closed this week." /> : (
                <ul>
                  {[...r.best, ...r.worst].map((x) => (
                    <ListRow key={x.symbol} title={bareSymbol(x.symbol)} right={inr(x.pnl, { sign: true })} rightTone={tone(x.pnl)} />
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Ideas">
              <div className="grid grid-cols-2 gap-3">
                {['taken', 'skipped'].map((k) => (
                  <Stat key={k} label={`${k[0].toUpperCase()}${k.slice(1)} (${r.ideas[k].n})`}
                    value={r.ideas[k].n ? pct(r.ideas[k].mean_excess, { sign: true }) : '—'}
                    delta={r.ideas[k].n ? 'avg vs NIFTY' : 'none scored yet'} tone={tone(r.ideas[k].mean_excess)} />
                ))}
              </div>
            </Card>
            <Card title="Journal">
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Trades" value={String(r.journal.trades)} />
                <Stat label="Net" value={inr(r.journal.net, { sign: true })} tone={tone(r.journal.net)} />
                <Stat label="Charges" value={inr(r.journal.charges)} />
              </div>
            </Card>
          </div>
        )}
    </Layout>
  );
};

export default WeeklyReport;
