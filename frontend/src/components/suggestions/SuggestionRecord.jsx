import React, { useState } from 'react';
import { Check, X, Loader2, Quote } from 'lucide-react';
import { Money, Stamp, Field, Scrip } from '../doc/Doc';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { formatCurrency, formatQuantity, formatTimeAgo } from '../../utils/formatters';
import { cn } from '../../utils/cn';
import Markdown from '../common/Markdown';

/**
 * One proposal, printed as a record on the note.
 *
 * The engine already sized this trade, set its stop and target and scored it,
 * so the record shows all of it: refusing to state the risk would make Approve
 * a guess. The conviction bar draws the AI cap as a printed limit mark,
 * because "the AI cannot rescue a trade the rules did not support" is the
 * product's actual claim and it should be visible, not documented.
 */

const AI_CAP = 0.3;

const Conviction = ({ score }) => {
  const final = Math.max(0, Math.min(1, score?.final ?? 0));
  const rule = Math.max(0, Math.min(1, score?.rule ?? 0));
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <span className="field-label">Conviction</span>
        <span className="figure-md text-sm">{final.toFixed(2)}</span>
      </div>
      <div
        className="relative h-2.5 border border-[var(--rule-strong)] bg-[var(--paper-sunk)]"
        role="img"
        aria-label={`Conviction ${final.toFixed(2)} of 1.00, rule component ${rule.toFixed(2)}, AI influence capped at ${AI_CAP}`}
      >
        <div
          className="absolute inset-y-0 left-0 bg-[var(--ink)]"
          style={{ width: `${final * 100}%` }}
        />
        {/* The printed limit mark: AI can move the score at most this far. */}
        <div
          className="absolute inset-y-[-3px] w-px bg-[var(--stamp)]"
          style={{ left: `${(1 - AI_CAP) * 100}%` }}
        />
      </div>
      <p className="doc-meta mt-1 normal-case">
        Rule {rule.toFixed(2)} · AI weighted to {AI_CAP.toFixed(2)} max
      </p>
    </div>
  );
};

const SuggestionRecord = ({ suggestion, onApprove, onReject }) => {
  const [busy, setBusy] = useState(null);
  const [failure, setFailure] = useState(null);

  const decided = suggestion.status !== 'PENDING';
  const risk = suggestion.entry_ref - suggestion.stop;
  const reward = suggestion.target - suggestion.entry_ref;
  const ratio = risk > 0 ? reward / risk : null;

  const act = async (kind) => {
    setBusy(kind);
    setFailure(null);
    try {
      await (kind === 'approve' ? onApprove() : onReject());
    } catch (err) {
      setFailure(
        err?.response?.data?.detail ||
          (kind === 'approve' ? 'Could not place the order' : 'Could not record the decision')
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <article
      className={cn(
        'sheet p-4 relative',
        decided && 'opacity-75'
      )}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-lg"><Scrip symbol={suggestion.symbol} /></h3>
            <Badge variant={suggestion.side === 'BUY' ? 'success' : 'destructive'}>
              {suggestion.side}
            </Badge>
            <Badge variant="secondary">{suggestion.mode === 'INTRADAY' ? 'MIS' : 'CNC'}</Badge>
          </div>
          <p className="doc-meta mt-1 normal-case">
            {formatQuantity(suggestion.quantity)} sh · {formatCurrency(suggestion.notional)} ·{' '}
            proposed {formatTimeAgo(suggestion.created_at)}
          </p>
        </div>

        {decided && (
          <Stamp
            animate
            label={suggestion.status === 'EXECUTED' ? 'Executed' : suggestion.status}
            tone={
              suggestion.status === 'EXECUTED'
                ? 'gain'
                : suggestion.status === 'REJECTED'
                  ? 'loss'
                  : 'stamp'
            }
          />
        )}
      </header>

      <div className="mt-4 grid grid-cols-3 gap-3 py-3 border-y border-[var(--rule)]">
        <Field label="Entry ref" value={formatCurrency(suggestion.entry_ref)} />
        <Field label="Stop" value={formatCurrency(suggestion.stop)} tone="down" />
        <Field label="Target" value={formatCurrency(suggestion.target)} tone="up" />
      </div>

      <div className="mt-3 flex items-baseline justify-between gap-4">
        <span className="field-label">Risk / reward</span>
        <span className="figure-md text-sm">
          {ratio ? `1 : ${ratio.toFixed(2)}` : '—'}
          <span className="text-[var(--ink-faint)]">
            {' '}
            (risk <Money value={-Math.abs(risk * suggestion.quantity)} />)
          </span>
        </span>
      </div>

      <div className="mt-4">
        <Conviction score={suggestion.score} />
      </div>

      {suggestion.reason_codes?.length > 0 && (
        <div className="mt-4">
          <p className="field-label mb-1.5">Grounds</p>
          <div className="flex flex-wrap gap-1.5">
            {suggestion.reason_codes.map((code) => (
              <Badge key={code} variant="outline">
                {code.replace(/_/g, ' ')}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {suggestion.ai_thesis && (
        <blockquote className="mt-4 pl-3 border-l border-[var(--stamp)] text-sm text-[var(--ink-soft)] leading-relaxed">
          <p className="field-label mb-1 flex items-center gap-1">
            <Quote className="w-3 h-3 text-[var(--stamp)]" aria-hidden="true" />
            Thesis
          </p>
          <Markdown>{suggestion.ai_thesis}</Markdown>
        </blockquote>
      )}

      {failure && (
        <p className="mt-3 text-sm text-[var(--loss)] border border-[var(--loss)] bg-[var(--loss-wash)] px-3 py-2">
          {failure}
        </p>
      )}

      {!decided && (
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Button
            variant="secondary"
            onClick={() => act('reject')}
            disabled={busy !== null}
            aria-label={`Decline ${suggestion.symbol}`}
          >
            {busy === 'reject' ? <Loader2 className="w-4 h-4 animate-spin" /> : <X className="w-4 h-4" />}
            Decline
          </Button>
          <Button
            variant="approve"
            onClick={() => act('approve')}
            disabled={busy !== null}
            aria-label={`Approve ${suggestion.symbol} and place the order`}
          >
            {busy === 'approve' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Check className="w-4 h-4" />
            )}
            Approve
          </Button>
        </div>
      )}

      {decided && suggestion.reason && (
        <p className="mt-3 doc-meta normal-case">Noted: {suggestion.reason}</p>
      )}
    </article>
  );
};

export default SuggestionRecord;
