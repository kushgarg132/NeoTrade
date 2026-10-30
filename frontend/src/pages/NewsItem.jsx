import React from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Badge from '../components/ui/Badge';
import useStored from '../hooks/useStored';
import { endpoints } from '../utils/api';
import { pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import { stockPath } from '../utils/stocks';
import { sectorPath } from '../utils/routes';
import { sourceName, targetCalls } from '../utils/newsItem';
import { formatDateTime, formatTimeAgo } from '../utils/formatters';
import { impactWord } from '../utils/market';

/** Stock and sector targets link to their pages; the market itself has none. */
const targetLink = (i) => (i.type === 'symbol' ? stockPath(i.target) : i.type === 'sector' ? sectorPath(i.target) : null);
const KIND = { symbol: 'Stock', sector: 'Sector', market: 'Market' };
const SCOPE = { COMPANY: 'Company', SECTOR: 'Sector', MARKET: 'Market', MACRO: 'Macro', GLOBAL: 'Global' };
const VERDICT = {
  right: { kind: 'proven', label: 'Played out' },
  wrong: { kind: 'alert', label: 'Went the other way' },
  flat: { kind: 'neutral', label: 'No real move' },
  pending: { kind: 'neutral', label: 'Too early to tell' },
};

const Panel = ({ children, className = '' }) => (
  <section className={`rounded-[20px] border border-[var(--border)] bg-[var(--surface)] p-4 ${className}`}>{children}</section>
);

/** The call's strength as ten segments, filled to `impact` in the called direction's colour. */
const Strength = ({ impact, direction }) => {
  const n = Math.round(impact ?? 0);
  const fill = direction > 0 ? 'bg-[var(--gain)]' : direction < 0 ? 'bg-[var(--loss)]' : 'bg-[var(--text-muted)]';
  return (
    <div className="flex gap-0.5" role="img" aria-label={`Impact ${n} of 10`}>
      {Array.from({ length: 10 }, (_, k) => <span key={k} className={`h-1.5 flex-1 rounded-full ${k < n ? fill : 'bg-[var(--surface-2)]'}`} />)}
    </div>
  );
};

/** One target: what the scorer called, then what it did after 1 hour, 1 day and 5 days, and whether the call held. */
const Call = ({ c }) => {
  const to = targetLink(c);
  const label = c.type === 'market' ? 'Market' : c.target;
  const way = c.direction > 0 ? 'Up' : c.direction < 0 ? 'Down' : 'Mixed';
  const v = VERDICT[c.verdict];
  return (
    <li className="py-4 border-b border-[var(--border)] last:border-b-0 first:pt-1">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {to
            ? <Link to={to} className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)] hover:underline underline-offset-4">{label}</Link>
            : <span className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">{label}</span>}
          <div className="text-[12px] text-[var(--text-muted)]">{KIND[c.type] || c.type}{c.horizon ? ` · over ${c.horizon}` : ''}</div>
        </div>
        <Badge kind={v.kind}>{v.label}{c.at && c.verdict !== 'pending' ? ` · ${c.at}` : ''}</Badge>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <span className={`w-[104px] shrink-0 text-[14px] font-semibold ${toneText(tone(c.direction))}`}>
          {c.direction > 0 ? '↑' : c.direction < 0 ? '↓' : '·'} {way} · {impactWord(c.impact)}
        </span>
        <div className="flex-1 sm:max-w-xs"><Strength impact={c.impact} direction={c.direction} /></div>
        <span className="w-9 shrink-0 text-right text-[12px] tabular-nums text-[var(--text-muted)]">{Math.round(c.impact ?? 0)}/10</span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {c.moves.map((m) => (
          <div key={m.h} className="rounded-[12px] bg-[var(--surface-2)] px-2.5 py-2 tabular-nums">
            <div className="text-[12px] text-[var(--text-muted)]">After {m.h}</div>
            {m.move == null ? <div className="text-[15px] text-[var(--text-muted)]">–</div> : (
              <>
                <div className={`text-[15px] font-semibold ${toneText(tone(m.move))}`}>{pct(m.move, { sign: true, dp: 1 })}</div>
                {c.type !== 'market' && <div className={`text-[12px] ${toneText(tone(m.edge))}`}>{pct(m.edge, { sign: true, dp: 1 })} vs Nifty</div>}
              </>
            )}
          </div>
        ))}
      </div>
    </li>
  );
};

const NewsItem = () => {
  const { id } = useParams();
  const { data, status, retry } = useStored(endpoints.newsItem(id));
  const calls = data ? targetCalls(data) : [];
  const judged = calls.filter((c) => c.verdict === 'right' || c.verdict === 'wrong');
  const right = judged.filter((c) => c.verdict === 'right').length;
  return (
    <Layout>
      <PageHeader title="Story" back="/market?tab=news" backLabel="News" />
      {status === 'loading' && <Skeleton rows={6} />}
      {status === 'empty' && <Empty title="Not found" body="This story is no longer stored." action={<Link to="/market?tab=news" className="text-[var(--accent)]">Back to News</Link>} />}
      {status === 'error' && <ErrorLine message="Could not load this story." onRetry={retry} />}
      {status === 'ok' && (
        <div className="space-y-4">
          <Panel>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-[var(--text-muted)]">
              {data.material && <Badge kind="alert">Material</Badge>}
              {SCOPE[data.scope] && <Badge>{SCOPE[data.scope]}</Badge>}
              <span>{[sourceName(data.source), formatTimeAgo(data.published_at)].filter(Boolean).join(' · ')}</span>
            </div>
            <h2 className="mt-2 text-[20px] font-bold leading-snug tracking-[-0.015em] text-[var(--text)] [text-wrap:pretty]">{data.title}</h2>
            <p className="mt-1 text-[12px] text-[var(--text-muted)]">{formatDateTime(data.published_at)}</p>
            {data.event && data.event !== data.title && (
              <div className="mt-4 rounded-[16px] bg-[var(--surface-2)] p-3">
                <p className="text-[12px] font-medium text-[var(--text-muted)]">AI read</p>
                <p className="mt-0.5 text-[15px] leading-snug text-[var(--text)]">{data.event}</p>
                {data.themes?.filter((t) => t !== 'other').length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">{data.themes.filter((t) => t !== 'other').map((t) => <Badge key={t}>{t}</Badge>)}</div>
                )}
              </div>
            )}
            {data.url && (
              <a href={data.url} target="_blank" rel="noopener noreferrer"
                className="tap mt-4 inline-flex min-h-11 w-full sm:w-auto items-center justify-center gap-1.5 rounded-[12px] border border-[var(--border)] bg-[var(--surface-2)] px-4 text-[15px] font-semibold text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
                Read the article <ArrowUpRight className="w-4 h-4" aria-hidden="true" />
              </a>
            )}
          </Panel>

          <Panel>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h2 className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">The call and what happened</h2>
              {judged.length > 0 && <span className="text-[13px] tabular-nums text-[var(--text-muted)]">{right} of {judged.length} played out</span>}
            </div>
            <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">What the AI expected each name to do, then its move after 1 hour, 1 day and 5 days against the Nifty.</p>
            {calls.length
              ? <ul className="mt-3">{calls.map((c) => <Call key={`${c.type}-${c.target}`} c={c} />)}</ul>
              : <Empty title="Not scored yet" body="The call appears once the news desk has scored this story; moves fill in after 1 hour, 1 day and 5 days." />}
          </Panel>
        </div>
      )}
    </Layout>
  );
};

export default NewsItem;
