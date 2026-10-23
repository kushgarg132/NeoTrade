import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
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
import { useLoad } from '../components/ideas/useLoad';
import Badge from '../components/ui/Badge';
import { useForward } from '../components/ForwardBadge';
import api, { endpoints } from '../utils/api';
import { recordLine, statusOf } from '../utils/library';
import { ideaFromSuggestion, ideaFromPick, parseIdeaId, GRADES } from '../utils/ideas';
import { bareSymbol, formatDateTime } from '../utils/formatters';
import NewsChip from '../components/common/NewsChip';
import useSymbolNews from '../hooks/useSymbolNews';
import useStored from '../hooks/useStored';
import { oneLine } from '../utils/aiText';
import { inr, pct } from '../components/ui/format';
import { toneText } from '../components/ui/tone';
import { AiLabel, AiText } from '../components/ai/AiSummary';
import { px, rewardRisk } from '../components/ideas/levels';
import { splitThesis } from '../utils/aiText';

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
  <details className="rounded-[16px] border border-[var(--border)] bg-[var(--surface)]">
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
      {why && <AiText text={why} />}
      {risk && (
        <div className="mt-3">
          <div className="text-[13px] font-semibold text-[var(--warn)]">What could go wrong</div>
          <AiText text={risk} className="text-[var(--text-muted)]" />
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
          <AiText text={text} />
        </div>
      )}
      <NewsChip entry={news[sym]} />
    </div>
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
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-semibold text-[var(--text-muted)]">{idea.side}</span>
        <span className="text-[13px] text-[var(--text-muted)]">{idea.setup}{idea.horizon ? ` · ${idea.horizon}d` : ''}</span>
        <IdeaBadge badge={idea.badge} />
        {idea.noEdge && <span className="text-[12px] font-semibold text-[var(--warn)]">No edge</span>}
        {GRADES[idea.grade] && <Badge kind={GRADES[idea.grade].kind}>{GRADES[idea.grade].label}</Badge>}
        {idea.decided && <Badge kind="neutral">{STATUS[idea.status] || idea.status}</Badge>}
      </div>

      <Card title="Trade plan" action={<Badge kind="paper">Paper</Badge>}>
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Entry" value={px(idea.entry)} />
          <Stat label="Stop" value={px(idea.stop)} delta={idea.toStop != null ? pct(idea.toStop, { sign: true, dp: 1 }) : null} tone="loss" />
          <Stat label="Target" value={px(idea.target)} />
        </div>
        <div className="mt-3 grid grid-cols-3 gap-3">
          <Stat label="R:R (reward : risk)" value={rewardRisk(idea) != null ? `${rewardRisk(idea).toFixed(1)} : 1` : '—'} />
          {idea.kind === 'p' && idea.entryZone && <Stat label="Buy up to" value={px(idea.entryZone[1])} />}
          {idea.kind === 'p' && idea.stretch != null && <Stat label="Stretch" value={px(idea.stretch)} />}
          {idea.kind === 's' && idea.headline?.value != null && <Stat label="If it hits target" value={<span className="text-[var(--gain)]">{pct(idea.headline.value, { sign: true, dp: 1 })}</span>} />}
        </div>
        {idea.qty != null && (
          <div className="mt-3 grid grid-cols-3 gap-3">
            <Stat label="Quantity" value={idea.qty} />
            <Stat label="Size" value={inr(idea.notional)} />
            <Stat label="Risk if stopped" value={inr(idea.risk)} />
          </div>
        )}
        {idea.score && <div className="mt-3"><Confidence score={idea.score} /></div>}
        <p className="mt-3 text-[12px] text-[var(--text-muted)]">
          Paper record · not advice.{idea.kind === 'p' ? " Levels come from this setup's past range; they are not a promise." : ' Levels are the engine\'s, set when the idea was made.'}
        </p>
      </Card>

      {idea.kind === 's' && !idea.decided && <BuyBar idea={idea} id={key} onDone={done} />}

      <Fold title="Why this idea">
        {idea.why && <p className="text-[15px] text-[var(--text)]">{idea.why}</p>}
        {idea.reasons.length > 0 && <ul className="list-disc pl-5 text-[15px] text-[var(--text)]">{idea.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        {!idea.why && !idea.reasons.length && !idea.thesis && <p className="text-[14px] text-[var(--text-muted)]">No reasons recorded.</p>}
        {idea.kind === 'p' && <PickContext symbol={idea.symbol} />}
        {idea.thesis && <Thesis text={idea.thesis} at={idea.createdAt} />}
      </Fold>

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
              </div>
              <p className="mt-3 text-[12px] text-[var(--text-muted)]">Out-of-sample = tested on past data held back from tuning the setup. n = events counted. t-score: above about 2 means the edge is unlikely to be luck.</p>
            </div>
          )}
        </Fold>
      )}

      {idea.kind === 'p' && idea.expectedMedian != null && (
        <Card title="Expected return" action={<Badge kind="paper">Paper</Badge>}>
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className={`text-[24px] font-semibold tabular-nums ${toneText(idea.expectedMedian > 0 ? 'gain' : idea.expectedMedian < 0 ? 'loss' : 'neutral')}`}>{pct(idea.expectedMedian, { sign: true, dp: 1 })}</span>
            {idea.when && <span className="text-[14px] text-[var(--text-muted)]">{idea.when}</span>}
          </div>
          {idea.rupees && <p className="mt-1 text-[14px] text-[var(--text)] tabular-nums">{idea.rupees}</p>}
          {idea.spread && <p className="mt-1 text-[13px] text-[var(--text-muted)] tabular-nums">Range {pct(idea.spread.p10, { sign: true, dp: 1 })} to {pct(idea.spread.p90, { sign: true, dp: 1 })} (10th to 90th percentile: 8 in 10 similar past cases landed in this band)</p>}
        </Card>
      )}

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
          {idea.features.length > 0 && (
            <ul className="mt-3 list-disc pl-5 text-[14px] text-[var(--text-muted)]">{idea.features.map((f) => <li key={f}>{f}</li>)}</ul>
          )}
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Stat label="Chance up (past similar cases)" value={pct(idea.pUp, { dp: 0 })} />
            <Stat label="Beat NIFTY" value={pct(idea.pBeat, { dp: 0 })} />
          </div>
        </Card>
      )}
    </div>
  );

  return (
    <Layout>
      <PageHeader title={idea ? bareSymbol(idea.symbol) : 'Idea'} back="/ideas" />
      {body}
    </Layout>
  );
};

export default IdeaDetail;
