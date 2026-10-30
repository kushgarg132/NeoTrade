import React, { useState } from 'react';
import { ImpactChips, NewsLink } from '../common/NewsImpacts';
import { Link } from 'react-router-dom';
import { ChevronRight, ArrowUp, ArrowDown, Minus } from 'lucide-react';
import IdeaBadge from './IdeaBadge';
import BuyBar from './BuyBar';
import Button from '../ui/Button';
import OrderTicket from '../trading/OrderTicket';
import api, { endpoints } from '../../utils/api';
import Badge from '../ui/Badge';
import GradeTile from '../ui/GradeTile';
import { px, rewardRisk as rr } from './levels';
import { olderPickLabel, GRADES, parseIdeaId, rangeBar } from '../../utils/ideas';
import { bareSymbol } from '../../utils/formatters';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { badNewsSince, resultsFlag, tone as newsTone } from '../../utils/news';

const DIRECTION = {
  pos: { Icon: ArrowUp, label: 'Good', cls: 'bg-[var(--gain-soft)] text-[var(--gain)]' },
  neg: { Icon: ArrowDown, label: 'Bad', cls: 'bg-[var(--loss-soft)] text-[var(--loss)]' },
  flat: { Icon: Minus, label: 'Mixed', cls: 'bg-[var(--surface-2)] text-[var(--text-muted)]' },
};

/** The stock's latest material headline (GET /news/symbols), one tappable line with a direction chip that opens its
 * analysis, and the analysis chips under it. Outside the row's Link: links may not nest. */
const Headline = ({ entry }) => {
  if (!entry?.material || !entry.headline) return null;
  const d = DIRECTION[newsTone({ direction: entry.direction })] || DIRECTION.flat;
  const body = (
    <>
      <span className={`inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 min-h-6 text-[12px] font-semibold ${d.cls}`}>
        <d.Icon className="w-3 h-3" aria-hidden="true" />{d.label}
      </span>
      <span className="truncate">{entry.headline}</span>
    </>
  );
  const cls = 'flex items-center gap-2 min-h-11 min-w-0 text-[13px] text-[var(--text-muted)]';
  return (
    <div className="pb-2">
      <NewsLink id={entry.id} url={entry.url} className={`${cls} hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`}>{body}</NewsLink>
      <ImpactChips impacts={entry.impacts} className="-mt-1.5" />
    </div>
  );
};

/** A pick's own actions: Skip hides it from this list (`POST /picks/{id}/dismiss`); Buy opens the
 * order ticket at the pick's entry, limited to the top of its entry zone (real money keeps the ticket's second tap). */
const PickBar = ({ idea, onDone }) => {
  const [ticket, setTicket] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(null);
  const skip = async () => {
    setBusy(true);
    setFailure(null);
    try {
      await api.post(endpoints.picks.dismiss(parseIdeaId(idea.id).key));
      onDone();
    } catch {
      setFailure('Could not skip this pick');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2">
      {failure && <p role="alert" className="text-[14px] text-[var(--loss)]">{failure}</p>}
      <div className="flex gap-2">
        <Button variant="secondary" className="px-6" onClick={skip} disabled={busy}>Skip</Button>
        <Button className="flex-1" onClick={() => setTicket(true)} disabled={busy}>Buy</Button>
      </div>
      {ticket && <OrderTicket symbol={idea.symbol} side="BUY" lastPrice={idea.entry} limitPrice={idea.entryZone?.[1]} onClose={() => setTicket(false)} onDone={onDone} />}
    </div>
  );
};

/** Entry / SL / T as three cells; stop and target also say how far they sit from entry. A pick's plan is to hold to
 * its due date (it beat selling at the levels in every setup, backend/forecast/study.py::levels_exit), so it says so. */
const Levels = ({ idea }) => {
  const from = (x) => (x != null && idea.entry ? x / idea.entry - 1 : null);
  const cell = (label, value, move) => (
    <div className="min-w-0 px-3 py-2">
      <div className="text-[12px] text-[var(--text-muted)]">{label}</div>
      <div className="text-[15px] font-semibold text-[var(--text)] tabular-nums truncate">{value != null ? px(value) : '–'}</div>
      {move != null && <div className={`text-[12px] tabular-nums ${toneText(tone(move))}`}>{pct(move, { sign: true, dp: 1 })}</div>}
    </div>
  );
  return (
    <div>
      <div className="grid grid-cols-3 divide-x divide-[var(--border)] rounded-[12px] bg-[var(--surface-2)]">
        {cell('Entry', idea.entry)}
        {cell('SL ', idea.stop, from(idea.stop))}
        {cell('Target', idea.target, from(idea.target))}
      </div>
      {idea.kind === 'p' && <div className="mt-1 text-[12px] text-[var(--text-muted)]">Hold to the due date · SL is protection · target is the best 10%</div>}
    </div>
  );
};

/** How sure the idea is, as a meter: an engine idea's composite score (rules plus a capped AI part) with High / Medium /
 * Low, or a pick's chance up (`p_up`): the setup's own past rate unless its similar-setups forecast passed validation
 * (`forecast: similar`), so picks of one setup share it. No High / Low for picks: single stocks over 20-60 days rarely
 * pass 60% up, and 55-58% is the edge (backend/forecast/similar.py::validate). The detail page splits the score. */
const Confidence = ({ idea }) => {
  const v = idea.score?.final ?? (idea.kind === 'p' ? idea.pUp : null);
  if (typeof v !== 'number') return null;
  const n = Math.round(v * 100);
  const pick = !idea.score;
  const note = pick ? (idea.forecast === 'similar' ? 'similar setups' : 'setup average') : n >= 65 ? 'High' : n >= 50 ? 'Medium' : 'Low';
  return (
    <div className="flex items-center gap-3 text-[12px] tabular-nums">
      <span className="w-[76px] shrink-0 text-[var(--text-muted)]">{pick ? 'Chance up' : 'Confidence'}</span>
      <div role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={n} aria-label={pick ? `Chance up ${n}%, ${note}` : `Confidence ${n}/100`}
        className="relative h-1.5 flex-1 rounded-full bg-[var(--surface-2)]">
        <div className="absolute inset-y-0 left-0 rounded-full bg-[var(--accent)]" style={{ width: `${Math.max(0, Math.min(100, n))}%` }} />
      </div>
      <span className="shrink-0 text-right"><b className="text-[var(--text)]">{pick ? `${n}%` : `${n}/100`}</b> <span className="text-[var(--text-muted)]">{note}</span></span>
    </div>
  );
};

/** A pick's likely range (p10 to p90) as a thin bar with the median tick and zero line, how it does against NIFTY under it. */
const Range = ({ idea }) => {
  const r = rangeBar(idea.spread.p10, idea.expectedMedian ?? (idea.spread.p10 + idea.spread.p90) / 2, idea.spread.p90);
  const odds = [idea.exMedian != null && `vs NIFTY ${pct(idea.exMedian, { sign: true, dp: 1 })}`,
    idea.pBeat != null && `beats it ${pct(idea.pBeat, { dp: 0 })}`].filter(Boolean).join(' · ');
  return (
    <div>
      <div className="flex items-center gap-2 text-[12px] tabular-nums text-[var(--text-muted)]">
        <span className="w-12 shrink-0">{pct(idea.spread.p10, { sign: true, dp: 1 })}</span>
        <div role="img" aria-label={`Likely range ${pct(idea.spread.p10, { sign: true, dp: 1 })} to ${pct(idea.spread.p90, { sign: true, dp: 1 })}`}
          className="relative h-1.5 flex-1 rounded-full bg-[var(--surface-2)]">
          <div className="absolute -inset-y-1 w-px bg-[var(--text-muted)]" style={{ left: `${r.zero}%` }} />
          <div className="absolute inset-y-0 rounded-full bg-[var(--accent)] opacity-40" style={{ left: `${r.p10}%`, width: `${r.p90 - r.p10}%` }} />
          <div className="absolute -inset-y-1 w-1 rounded-full bg-[var(--accent)]" style={{ left: `calc(${r.median}% - 2px)` }} />
        </div>
        <span className="w-12 shrink-0 text-right">{pct(idea.spread.p90, { sign: true, dp: 1 })}</span>
      </div>
      {odds && <div className="mt-1 text-[12px] text-[var(--text-muted)] tabular-nums">{odds}</div>}
    </div>
  );
};

/** One idea as its own card: grade, symbol and setup beside the headline move; Entry / SL / T and R:R; the likely
 * range; flags; the latest headline; then a pending engine idea's or a pick's own Skip / Buy. */
const IdeaRow = ({ idea, onDone, news, results }) => {
  const key = bareSymbol(idea.symbol)?.toUpperCase();
  const entry = news?.[key];
  const resultsSoon = resultsFlag(results?.[key], idea.daysSince > 0 && idea.daysLeft != null ? idea.daysLeft : idea.horizon);
  const badSince = idea.kind === 'p' && idea.daysSince > 0 && badNewsSince(entry, idea.firedOn);
  const older = olderPickLabel(idea);
  const ratio = rr(idea);
  const actions = (idea.kind === 's' && !idea.decided && onDone) || (idea.kind === 'p' && onDone);
  return (
    <article className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
      <Link to={`/ideas/${encodeURIComponent(idea.id)}`} className="tap block p-4 space-y-3 active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)]">
        <div className="flex items-start gap-3">
          {GRADES[idea.grade] && <span className="shrink-0"><GradeTile grade={idea.grade} /></span>}
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[12px] font-semibold text-[var(--text-muted)]">{idea.side}</span>
              <span className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)] truncate">{bareSymbol(idea.symbol)}</span>
            </div>
            <div className="flex min-w-0 gap-1 text-[13px] text-[var(--text-muted)]">
              <span className="truncate">{idea.setup}{idea.horizon && !older && idea.headline?.value == null ? ` · ${idea.horizon}d` : ''}</span>
              {ratio != null && <span className="shrink-0 whitespace-nowrap">· <span className="font-semibold text-[var(--text)] tabular-nums">R:R {ratio.toFixed(1)}</span></span>}
            </div>
          </div>
          {idea.headline?.value != null && (
            <div className="shrink-0 text-right tabular-nums">
              <div className={`text-[22px] font-bold leading-none tracking-[-0.02em] ${toneText(tone(idea.headline.value))}`}>{pct(idea.headline.value, { sign: true, dp: 1 })}</div>
              <div className="mt-1 text-[12px] text-[var(--text-muted)] whitespace-nowrap">{idea.kind === 'p' && idea.horizon && !older ? `in ${idea.horizon} days` : idea.headline.label}</div>
            </div>
          )}
          <ChevronRight className="w-4 h-4 mt-1 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
        </div>

        {(idea.badge || idea.experimental || resultsSoon || badSince) && (
          <div className="flex flex-wrap items-center gap-1.5 empty:hidden">
            <IdeaBadge badge={idea.badge} />
            {idea.experimental && <Badge>Experimental</Badge>}
            {resultsSoon && <Badge kind="unproven">{resultsSoon}</Badge>}
            {badSince && <Badge kind="alert">Bad news since signal</Badge>}
          </div>
        )}

        <Confidence idea={idea} />
        {idea.entry != null && <Levels idea={idea} />}
        {idea.kind === 'p' && idea.spread && <Range idea={idea} />}

        {(older || idea.basket) && (
          <div className="space-y-0.5 text-[12px] text-[var(--text-muted)] tabular-nums">
            {older && <div>{older}</div>}
            {idea.basket && (
              <div>
                <span className={toneText(idea.basket.beat_nifty >= 0.6 ? 'gain' : 'neutral')}>Monthly basket beat NIFTY in {pct(idea.basket.beat_nifty, { dp: 0 })} of months</span>
                {' · '}median {pct(idea.basket.median_vs_nifty, { sign: true, dp: 1 })}
              </div>
            )}
          </div>
        )}
      </Link>
      {entry?.material && entry.headline && <div className="px-4 border-t border-[var(--border)]"><Headline entry={entry} /></div>}
      {actions && (
        <div className="px-4 pb-4 pt-1">
          {idea.kind === 's' && !idea.decided && onDone && <BuyBar idea={idea} id={parseIdeaId(idea.id).key} onDone={onDone} compact />}
          {idea.kind === 'p' && onDone && <PickBar idea={idea} onDone={onDone} />}
        </div>
      )}
    </article>
  );
};

export default IdeaRow;
