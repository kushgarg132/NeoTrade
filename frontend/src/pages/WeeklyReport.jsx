import React, { useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Hero from '../components/ui/Hero';
import Stat from '../components/ui/Stat';
import ListRow from '../components/ui/ListRow';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import { useLoad } from '../components/ideas/useLoad';
import AiSummary from '../components/ai/AiSummary';
import api, { endpoints } from '../utils/api';
import { bareSymbol } from '../utils/formatters';
import { inr, pct, tone } from '../components/ui/format';
import { stockPath } from '../utils/stocks';
import { shiftWeek, weekRange } from '../utils/weekly';

const act = 'inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[15px] font-semibold';
const navCls = 'inline-flex items-center justify-center min-h-11 min-w-11 text-[var(--text-muted)] disabled:opacity-40';

const muted = 'text-[13px] text-[var(--text-muted)]';
const openUrl = (url) => () => window.open(url, '_blank', 'noopener,noreferrer');

/** The week's news on the user's holdings (backend/portfolio/news_moves.py::week): big moves against NIFTY with
 * the items published before them, the themes that touched the book, and the measured 5-day hit rate. */
const NewsWeek = ({ news }) => {
  const acc = news.accuracy;
  return (
    <Card title="News on your holdings" action={<span className={muted}>context, not advice</span>}>
      {news.movers.length === 0
        ? <p className={muted}>No holding moved more than 4% against NIFTY this week.</p>
        : (
          <ul>
            {news.movers.map((m) => (
              <ListRow key={m.symbol} dense privateValue={false} title={bareSymbol(m.symbol)}
                sub={m.items[0]?.title || 'No news found before the move'}
                right={`${pct(m.vs_nifty == null ? m.move_pct / 100 : m.vs_nifty / 100, { sign: true, dp: 1 })}${m.vs_nifty == null ? '' : ' vs NIFTY'}`}
                rightTone={tone(m.vs_nifty ?? m.move_pct)} onClick={m.items[0]?.url ? openUrl(m.items[0].url) : undefined} />
            ))}
          </ul>
        )}
      {news.themes.length > 0 && (
        <div className="mt-3 pt-3 border-t border-[var(--border)]">
          <div className="text-[13px] font-semibold text-[var(--text-muted)] mb-1">Themes that hit your book</div>
          <div className="flex flex-wrap gap-2">
            {news.themes.map((t) => (
              <Badge key={t.theme} kind="neutral">
                {t.theme} · {t.n} {t.direction > 0.2 ? 'good' : t.direction < -0.2 ? 'bad' : 'mixed'}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {acc && (
        <p className={`mt-3 ${muted}`}>
          How often news called the 5-day move against NIFTY:
          {acc.company && ` company news ${acc.company.hit_pct}%${acc.company.n ? ` of ${acc.company.n}` : ''}`}
          {acc.company && acc.sector && ','}
          {acc.sector && ` sector news ${acc.sector.hit_pct}%${acc.sector.n ? ` of ${acc.sector.n}` : ''}`}.
        </p>
      )}
    </Card>
  );
};

/** Last week for the user's own account; the same numbers Telegram sends on Sunday 18:00. */
const WeeklyReport = () => {
  const [params, setParams] = useSearchParams();
  const week = params.get('week');
  const { data: r, loading, error, reload } = useLoad(useCallback(
    () => api.get(endpoints.weeklyReport(week)).then((x) => x.data), [week]));
  const words = useLoad(useCallback(() => api.get(endpoints.summaries.weekly(week)).then((x) => x.data), [week]));
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
      <AiSummary title="The week in words" state={words} className="mb-4" emptyBody="Written on Sunday evening, with the report." />
      {loading ? <Skeleton rows={6} />
        : error ? <ErrorLine message="Couldn't load this week's report." onRetry={reload} />
        : (
          <div className="space-y-4">
            {r.you.ret == null ? (
              <Card title="Your account against NIFTY">
                <Empty title="No curve for this week" body="Your account's weekly return needs a connected broker or imported trades."
                  action={<Link to="/settings/brokers" className={act}>Connect your broker</Link>} />
              </Card>
            ) : (
              <Hero label="Your account this week" value={r.you.ret} format={(v) => pct(v, { sign: true })} privateValue={false}>
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <Stat label="NIFTY" value={pct(r.you.nifty, { sign: true })} tone={tone(r.you.nifty)} />
                  <Stat label="Excess" value={pct(r.you.excess, { sign: true })} tone={tone(r.you.excess)} />
                </div>
              </Hero>
            )}
            <Card title="AI book" to="/ai">
              <Stat label={<span className="inline-flex items-center gap-2">Paper return <Badge kind="paper">Paper</Badge></span>} value={pct(r.ai.ret, { sign: true })} tone={tone(r.ai.ret)} />
              <p className="mt-1 text-[13px] text-[var(--text-muted)]">Closed AI trades this week, after charges, as % of its capital.</p>
            </Card>
            <Card title="Best and worst" action={<span className="text-[13px] text-[var(--text-muted)]">your account, by stock</span>}>
              {r.best.length + r.worst.length === 0 ? <Empty title="No closed trades" body="Stocks you closed this week show here, best and worst first."
                action={<Link to="/journal" className={act}>Open the journal</Link>} /> : (
                <>
                  {[['Best', r.best], ['Worst', r.worst]].filter(([, l]) => l.length).map(([label, list]) => (
                    <div key={label}>
                      <div className="text-[13px] font-semibold text-[var(--text-muted)] mt-1">{label}</div>
                      <ul>
                        {list.map((x) => (
                          <ListRow key={x.symbol} dense to={stockPath(x.symbol)} title={bareSymbol(x.symbol)} right={inr(x.pnl, { sign: true })} rightTone={tone(x.pnl)} />
                        ))}
                      </ul>
                    </div>
                  ))}
                </>
              )}
            </Card>
            <Card title="Ideas" action={<Badge kind="paper">Paper</Badge>}>
              <p className="mb-2 text-[13px] text-[var(--text-muted)]">Paper-scored ideas decided this week, split by whether you traded them.</p>
              <div className="grid grid-cols-2 gap-3">
                {['taken', 'skipped'].map((k) => (
                  <Stat key={k} label={`${k[0].toUpperCase()}${k.slice(1)} (${r.ideas[k].n})`}
                    value={r.ideas[k].n ? pct(r.ideas[k].mean_excess, { sign: true }) : '—'}
                    delta={r.ideas[k].n ? 'avg better or worse than NIFTY' : 'none scored yet'} tone={tone(r.ideas[k].mean_excess)} />
                ))}
              </div>
            </Card>
            {r.news && <NewsWeek news={r.news} />}
            <Card title="Journal" to="/money?tab=journal">
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Trades" value={String(r.journal.trades)} />
                <Stat label="Net, after charges" value={inr(r.journal.net, { sign: true })} tone={tone(r.journal.net)} />
                <Stat label="Charges" value={inr(r.journal.charges)} />
              </div>
            </Card>
          </div>
        )}
    </Layout>
  );
};

export default WeeklyReport;
