import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import IdeaBadge from './IdeaBadge';
import BuyBar from './BuyBar';
import Button from '../ui/Button';
import OrderTicket from '../trading/OrderTicket';
import api, { endpoints } from '../../utils/api';
import Badge from '../ui/Badge';
import { px, rewardRisk as rr } from './levels';
import { olderPickLabel, GRADES, parseIdeaId } from '../../utils/ideas';
import { bareSymbol } from '../../utils/formatters';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';

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
      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" onClick={skip} disabled={busy}>Skip</Button>
        <Button onClick={() => setTicket(true)} disabled={busy}>{`Buy ${bareSymbol(idea.symbol)}…`}</Button>
      </div>
      {ticket && <OrderTicket symbol={idea.symbol} side="BUY" lastPrice={idea.entry} limitPrice={idea.entryZone?.[1]} onClose={() => setTicket(false)} onDone={onDone} />}
    </div>
  );
};

/** One idea in the list: action + symbol, setup and horizon, headline %, proven badge; a pending engine idea or a pick gets its own Skip / Buy bar. */
const IdeaRow = ({ idea, onDone }) => (
  <div className="py-1.5 border-b border-[var(--border)] last:border-b-0">
    <Link to={`/ideas/${encodeURIComponent(idea.id)}`} className="flex items-center gap-3 min-h-11 active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold text-[var(--text-muted)]">{idea.side}</span>
          <span className="text-[15px] font-semibold text-[var(--text)] truncate">{bareSymbol(idea.symbol)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 text-[13px] text-[var(--text-muted)]">
          <span>{idea.setup}{idea.horizon && !olderPickLabel(idea) ? ` · ${idea.horizon}d` : ''}</span>
          <span className="shrink-0"><IdeaBadge badge={idea.badge} /></span>
          {GRADES[idea.grade] && <span className="shrink-0"><Badge kind={GRADES[idea.grade].kind}>{GRADES[idea.grade].label}</Badge></span>}
          {idea.experimental && <span className="shrink-0"><Badge>Experimental</Badge></span>}
        </div>
        {idea.entry != null && (
          <div className="flex flex-wrap gap-x-2 text-[13px] text-[var(--text)] tabular-nums">
            <span className="whitespace-nowrap">Entry {px(idea.entry)}</span>
            {idea.stop != null && <span className="whitespace-nowrap">SL {px(idea.stop)}</span>}
            {idea.target != null && <span className="whitespace-nowrap">T {px(idea.target)}</span>}
            {rr(idea) != null && <span className="whitespace-nowrap font-semibold">R:R {rr(idea).toFixed(1)}</span>}
          </div>
        )}
        {olderPickLabel(idea) && <div className="text-[12px] text-[var(--text-muted)] tabular-nums">{olderPickLabel(idea)}</div>}
        {idea.kind === 'p' && idea.spread && (
          <div className="text-[12px] text-[var(--text-muted)] tabular-nums">
            Range {pct(idea.spread.p10, { sign: true, dp: 1 })} to {pct(idea.spread.p90, { sign: true, dp: 1 })}{idea.pUp != null ? ` · chance up ${pct(idea.pUp, { dp: 0 })}` : ''}
            {idea.exMedian != null && <span className="text-[12px]"> · vs NIFTY {pct(idea.exMedian, { sign: true, dp: 1 })}{idea.pBeat != null ? ` · beats ${pct(idea.pBeat, { dp: 0 })}` : ''}</span>}
          </div>
        )}
      </div>
      {idea.headline?.value != null && (
        <div className="shrink-0 max-w-[88px] text-right tabular-nums">
          <div className={`text-[15px] font-semibold ${toneText(tone(idea.headline.value))}`}>{pct(idea.headline.value, { sign: true, dp: 1 })}</div>
          <div className="text-[12px] text-[var(--text-muted)]">{idea.headline.label}{idea.kind === 'p' && idea.expectedMedian == null && idea.pBeat != null ? ` · beats ${pct(idea.pBeat, { dp: 0 })}` : ''}</div>
        </div>
      )}
      <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
    </Link>
    {idea.kind === 's' && !idea.decided && onDone && (
      <div className="mt-1.5"><BuyBar idea={idea} id={parseIdeaId(idea.id).key} onDone={onDone} compact /></div>
    )}
    {idea.kind === 'p' && onDone && <div className="mt-1.5"><PickBar idea={idea} onDone={onDone} /></div>}
  </div>
);

export default IdeaRow;
