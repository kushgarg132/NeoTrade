import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Stat from '../components/ui/Stat';
import Button from '../components/ui/Button';
import IdeaBadge from '../components/ideas/IdeaBadge';
import RangeBar from '../components/ideas/RangeBar';
import BuyBar from '../components/ideas/BuyBar';
import PickBar from '../components/ideas/PickBar';
import { useLoad } from '../components/ideas/useLoad';
import Badge from '../components/ui/Badge';
import GradeTile from '../components/ui/GradeTile';
import { useForward } from '../components/ForwardBadge';
import api, { endpoints } from '../utils/api';
import { recordLine, statusOf } from '../utils/library';
import { ideaFromSuggestion, ideaFromPick, parseIdeaId, pickStatus, GRADES } from '../utils/ideas';
import { bareSymbol, formatDateTime } from '../utils/formatters';
import NewsChip from '../components/common/NewsChip';
import useSymbolNews from '../hooks/useSymbolNews';
import useStored from '../hooks/useStored';
import { oneLine } from '../utils/aiText';
import { inr, pct, tone } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import LevelsLine from '../components/ideas/LevelsLine';
import { AiLabel, AiMarkdown, AiText } from '../components/ai/AiSummary';
import { px, rewardRisk } from '../components/ideas/levels';
import { splitThesis } from '../utils/aiText';
import { stockPath } from '../utils/stocks';
import StockIcon from '../components/ui/StockIcon';

const STATUS = { APPROVED: 'You bought this', REJECTED: 'You skipped this', EXPIRED: 'Expired', FILLED: 'Filled', CANCELLED: 'Cancelled' };
const PAPER = { 'live-ready': 'Paper record clears the live gate', paper: 'Paper record still building', untested: 'Not backtested yet', paused: 'Paused by the AI' };

/** One line: the composite score and how much of it is the rules versus the AI (the AI cannot rescue a trade the rules did not support). */
const Confidence = ({ score }) => (
  <p className="text-[14px] text-[var(--text)] tabular-nums" title="Composite score out of 100. The AI can move it only a little: it cannot rescue a trade the rules did not support.">
    Confidence <b>{Math.round(score.final * 100)}/100</b>
    {score.rule != null && <span className="text-[var(--text-muted)]"> · Rules {Math.round(score.rule * 100)} · AI {score.ai >= 0 ? '+' : '−'}{Math.abs(Math.round(score.ai * 100))}</span>}
  </p>
);

/** A folded section: a native details, so no JS and keyboard-friendly. */
const Fold = ({ title, children }) => (
  <details className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)]">
    <summary className="flex items-center min-h-11 px-4 text-[15px] font-semibold text-[var(--text)] cursor-pointer">{title}</summary>
    <div className="px-4 pb-4 space-y-3">{children}</div>
  </details>
);

/** Strategy track record: forward scorecard row (n/100, mean excess, hit rate) and the paper record. */
const StrategyRecord = ({ idea }) => {
  const rows = useForward();
  const row = rows.find((r) => r.source === 'suggestion' && r.name === idea.strategy);
  const [card, setCard] = useState(null);
  useEffect(() => {
    let live = true;
    api.get(endpoints.strategyLibrary()).then((r) => live && setCard(r.data.strategies.find((c) => c.name === idea.strategy) || null)).catch(() => {});
    return () => { live = false; };
  }, [idea.strategy]);
  if (!row && !card) return null;
  return (
    <div>
      {row && (
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Scored (of 100 needed)" value={`${Math.min(row.n, 100)}/100`} />
          <Stat label="Avg vs NIFTY" value={<span className={toneText(row.mean_excess > 0 ? 'gain' : row.mean_excess < 0 ? 'loss' : 'neutral')}>{pct(row.mean_excess, { sign: true })}</span>} />
          <Stat label="Hit rate" value={pct(row.hit_rate, { dp: 0 })} />
        </div>
      )}
      {card && (
        <p className={`${row ? 'mt-3 ' : ''}text-[14px] text-[var(--text-muted)]`}>
          Paper record: {recordLine(card)}. {PAPER[statusOf(card)]}.
        </p>
      )}
    </div>
  );
};

const find = async (kind, key) => {
  if (kind === 's') {
    // Pending first; a decided idea is found in the full history.
    const pending = (await api.get(endpoints.suggestions.list({ status: 'PENDING' }))).data.find((x) => x.id === key);
    const s = pending || (await api.get(endpoints.suggestions.list({ limit: 500 }))).data.find((x) => x.id === key);
    return s ? ideaFromSuggestion(s) : null;
  }
  const today = (await api.get(endpoints.picks.today)).data;
  // The served row carries the grade and entry-zone flags; a raw or past pick takes its setup's grade.
  const pick = (today.shown || []).find((p) => p._id === key) || today.picks.find((p) => p._id === key)
    || (await api.get(endpoints.picks.history(90))).data.picks.find((p) => p._id === key);
  return pick
    ? ideaFromPick({ grade: today.grades?.[pick.setup], ...pick }, today.setups.find((s) => s.setup === pick.setup), today.grade_text)
    : null;
};

/** The AI thesis saved with the suggestion, with its risk sentences set apart when it names any. */
const Thesis = ({ text, at }) => {
  const { why, risk } = splitThesis(text);
  return (
    <div>
      <AiLabel at={at} />
      {why && <AiText text={why} title="Why this idea" />}
      {risk && (
        <div className="mt-3">
          <div className="text-[13px] font-semibold text-[var(--warn)]">What could go wrong</div>
          <AiMarkdown text={risk} className="text-[var(--text-muted)]" ask={false} />
        </div>
      )}
    </div>
  );
};

/** A pick's context: the stock's stored AI note (no model call here) and its latest scored headline. */
const PickContext = ({ symbol }) => {
  const sym = bareSymbol(symbol);
  const note = useStored(endpoints.stockNote(sym));
  const { news } = useSymbolNews([sym]);
  const text = note.status === 'ok' ? oneLine(note.data.summary) : '';
  if (!text && !news[sym]) return null;
  return (
    <div className="mt-3 pt-3 border-t border-[var(--border)] space-y-2">
      {text && (
        <div>
          <span className="block text-[12px] text-[var(--text-muted)]">AI note{note.data?.as_of ? ` · ${formatDateTime(note.data.as_of)}` : ''}</span>
          <AiText text={text} title="Idea review" />
        </div>
      )}
      <NewsChip entry={news[sym]} />
    </div>
  );
};

const GRADE_NAME = { A: 'Proven setup', B: 'Promising setup', C: 'Unproven setup' };
const STATUS_TONE = { alert: 'text-[var(--loss)]', unproven: 'text-[var(--warn)]', neutral: 'text-[var(--text-muted)]', proven: 'text-[var(--gain)]' };

/** The top of an idea: grade and status, the setup and its time, then the expected move as the page's one big figure
 *  with how sure and the rupees per share under it. */
const Lead = ({ idea }) => {
  const status = pickStatus(idea);
  const broken = status?.label === 'Below stop';
  const move = idea.kind === 'p' ? idea.expectedMedian : idea.headline?.value;
  const time = idea.kind === 'p' && idea.daysSince > 0 && idea.daysLeft != null ? `${idea.daysLeft} days left` : idea.when;
  return (
    <section className="space-y-2" aria-label="Summary">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {GRADES[idea.grade] && (
          <span className="inline-flex items-center gap-2 text-[14px] font-semibold text-[var(--text)]">
            <GradeTile grade={idea.grade} small />{GRADE_NAME[idea.grade]}
          </span>
        )}
        {status && (
          <span className={`inline-flex items-center gap-1.5 text-[14px] font-medium ${STATUS_TONE[status.kind]}`}>
            <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />{status.label}
          </span>
        )}
        {idea.side !== 'BUY' && <Badge kind="alert">{idea.side}</Badge>}
        <IdeaBadge badge={idea.badge} />
        {idea.decided && <Badge kind="neutral">{STATUS[idea.status] || idea.status}</Badge>}
      </div>
      <p className="text-[14px] text-[var(--text-muted)]">
        {[idea.setup, idea.horizon && `${idea.horizon}-day hold`, time].filter(Boolean).join(' · ')}
        {idea.noEdge && <span className="text-[var(--warn)]"> · no edge over the average stock</span>}
      </p>
      {move != null && (
        <div className="pt-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className={`text-[28px] font-extrabold leading-none tracking-[-0.03em] tabular-nums ${broken ? 'text-[var(--text-muted)]' : toneText(tone(move))}`}>{pct(move, { sign: true, dp: 1 })}</span>
            <span className="text-[14px] text-[var(--text-muted)]">{idea.kind === 'p' ? 'expected' : idea.headline?.label}</span>
          </div>
          {broken && (
            <p className="mt-2 text-[14px] text-[var(--loss)]">
              Now {px(idea.priceNow)}, under the {px(idea.stop)} stop: the plan this forecast was made for has broken.
            </p>
          )}
          <p className="mt-1.5 text-[13px] tabular-nums text-[var(--text-muted)]">
            {[idea.rupees, idea.pUp != null && `${pct(idea.pUp, { dp: 0 })} chance up`, idea.pBeat != null && `${pct(idea.pBeat, { dp: 0 })} beat NIFTY`].filter(Boolean).join(' · ')}
          </p>
        </div>
      )}
    </section>
  );
};

const IdeaDetail = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const ref = parseIdeaId(id);
  const kind = ref?.kind;
  const key = ref?.key;
  const { data: idea, loading, error, reload } = useLoad(useCallback(() => (kind ? find(kind, key) : Promise.resolve(null)), [kind, key]));
  const done = () => navigate('/ideas', { replace: true });

  let body;
  if (loading) body = <Skeleton rows={6} />;
  else if (error) body = <ErrorLine message="Could not load this idea." onRetry={reload} />;
  else if (!idea) body = <Empty title="Idea not found" body="It may have been decided or has expired." action={<Button variant="secondary" onClick={done}>Back to Ideas</Button>} />;
  else body = (
    <div className="space-y-4">
      <Lead idea={idea} />

      <Card title="Trade plan" action={<Badge kind="paper">Paper</Badge>}>
        <LevelsLine stop={idea.stop} zone={idea.entryZone} entry={idea.entry} target={idea.target} now={idea.priceNow} />
        <div className="mt-4 pt-3 border-t border-[var(--border)] grid grid-cols-3 gap-3">
          <Stat label="Entry" value={px(idea.entry)} />
          <Stat label="To stop" value={pickStatus(idea)?.label === 'Below stop' ? <span className="text-[var(--loss)]">Broken</span>
            : idea.toStop != null ? <span className="text-[var(--loss)]">{pct(idea.toStop, { sign: true, dp: 1 })}</span> : '—'} />
          <Stat label="Reward : risk" value={rewardRisk(idea) != null ? `${rewardRisk(idea).toFixed(1)} : 1` : '—'} />
        </div>
        {idea.qty != null && (
          <div className="mt-3 grid grid-cols-3 gap-3">
            <Stat label="Quantity" value={idea.qty} />
            <Stat label="Size" value={inr(idea.notional)} />
            <Stat label="Risk if stopped" value={inr(idea.risk)} />
          </div>
        )}
        {idea.score && <div className="mt-3"><Confidence score={idea.score} /></div>}
        <p className="mt-3 text-[12px] leading-snug text-[var(--text-muted)]">
          Paper record · not advice.{idea.kind === 'p' ? " Hold to the due date: held, this setup's past picks earned more than when sold at the stop or target, so the stop is protection and the target is the best 10% of past outcomes, not a promise." : ' Levels are the engine\'s, set when the idea was made.'}
        </p>
      </Card>

      <Card title="Why this idea">
        <div className="space-y-3">
          {idea.why && <p className="text-[15px] leading-snug text-[var(--text)]">{idea.why}</p>}
          {idea.reasons.length > 0 && <ul className="list-disc pl-5 text-[15px] text-[var(--text)]">{idea.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
          {!idea.why && !idea.reasons.length && !idea.thesis && <p className="text-[14px] text-[var(--text-muted)]">No reasons recorded.</p>}
          {idea.kind === 'p' && <PickContext symbol={idea.symbol} />}
          {idea.thesis && <Thesis text={idea.thesis} at={idea.createdAt} />}
        </div>
      </Card>

      {idea.range && (
        <Card title={idea.excessRange ? 'Likely result vs NIFTY' : 'Likely range'} action={<Badge kind="paper">Paper</Badge>}>
          {idea.forecast && (
            <p className="mb-3 text-[13px] text-[var(--text-muted)]">
              {idea.forecast === 'similar' && idea.similarN != null
                ? `Based on ${idea.similarN} similar past ${idea.setup} setups.`
                : 'Setup average: the similar-setup forecast did not beat it in testing.'}
            </p>
          )}
          <RangeBar range={idea.excessRange || idea.range} />
          {idea.spread && idea.excessRange && (
            <p className="mt-3 text-[13px] text-[var(--text-muted)] tabular-nums">
              On its own: {pct(idea.spread.p10, { sign: true, dp: 1 })} to {pct(idea.spread.p90, { sign: true, dp: 1 })}; 8 in 10 similar past cases landed in this band.
            </p>
          )}
          {idea.features.length > 0 && (
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {idea.features.map((f) => <li key={f} className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[12px] text-[var(--text)]">{f}</li>)}
            </ul>
          )}
        </Card>
      )}

      {((idea.kind === 's' && idea.strategy) || idea.pastN != null) && (
        <Fold title="Track record">
          <div className="flex items-center gap-2"><IdeaBadge badge={idea.badge} /><span className="text-[12px] text-[var(--text-muted)]">Forward n/100 = outcomes scored live so far, out of the 100 needed.</span></div>
          {idea.kind === 's' && idea.strategy && <StrategyRecord idea={idea} />}
          {idea.pastN != null && (
            <div>
              {idea.gradeText && <p className="mb-3 text-[14px] text-[var(--text-muted)]">{idea.gradeText}{idea.missedEntry ? '. The price is now past the entry zone (3% above the signal price).' : '.'}</p>}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Stat label="Past events" value={idea.pastN} />
                <Stat label="Out-of-sample vs NIFTY" value={pct(idea.oosExcess, { sign: true })} delta={idea.oosN != null ? `n ${idea.oosN}` : null} />
                <Stat label="vs the average stock" value={pct(idea.adjExcess, { sign: true })} delta={idea.adjT != null ? `t ${idea.adjT.toFixed(1)}` : null} />
                {idea.basket && <Stat label="Basket months beating NIFTY" value={pct(idea.basket.beat_nifty, { dp: 0 })} delta={`${idea.basket.months} months`} />}
                {idea.basket?.years_positive != null && <Stat label="Years ahead of the average stock" value={pct(idea.basket.years_positive, { dp: 0 })} />}
              </div>
              {idea.basket && <p className="mt-3 text-[13px] text-[var(--text)]">One stock over a few weeks is mostly noise, so its odds stay near a coin flip even when the setup works. Bought together each month, this setup's picks beat NIFTY in {pct(idea.basket.beat_nifty, { dp: 0 })} of months (median {pct(idea.basket.median_vs_nifty, { sign: true, dp: 1 })}). Spread money across its picks rather than betting on one.</p>}
              <p className="mt-3 text-[12px] text-[var(--text-muted)]">Out-of-sample = tested on past data held back from tuning the setup. n = events counted. t-score: above about 2 means the edge is unlikely to be luck.</p>
            </div>
          )}
        </Fold>
      )}

      {/* Skip / Buy sit in a fixed bar like the Stock page's Buy / Sell, so the decision is always one thumb away. */}
      {((idea.kind === 's' && !idea.decided) || idea.kind === 'p') && (
        <>
          <div className="h-28 lg:h-20" aria-hidden="true" />
          <div className="fixed z-30 inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] lg:bottom-0 lg:left-56 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-2">
            <div className="mx-auto max-w-5xl">
              {idea.kind === 's' && !idea.decided && <BuyBar idea={idea} id={key} onDone={done} />}
              {idea.kind === 'p' && <PickBar idea={idea} onDone={done} broken={pickStatus(idea)?.label === 'Below stop'} />}
            </div>
          </div>
        </>
      )}
    </div>
  );

  return (
    <Layout>
      <PageHeader title={idea ? <span className="flex min-w-0 items-center gap-2.5"><StockIcon symbol={idea.symbol} className="size-8 rounded-[8px] p-0.5" /><span className="truncate">{bareSymbol(idea.symbol)}</span></span> : 'Idea'} back="/ideas"
        right={idea && <Link to={stockPath(idea.symbol)} className="inline-flex items-center min-h-11 px-2 text-[14px] font-semibold text-[var(--accent)]">View stock</Link>} />
      {body}
    </Layout>
  );
};

export default IdeaDetail;
