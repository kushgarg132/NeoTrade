import React from 'react';
import { Stamp } from '../doc/Doc';

const TONE = { SELL: 'loss', REVIEW: 'loss', ADD: 'gain' };
const LABEL = { REVIEW: 'Review first' };

/** A holding's verdict as a stamp; nothing when there is none (verdicts hidden). */
const VerdictStamp = ({ verdict, compact = false }) =>
  verdict ? (
    <Stamp
      label={LABEL[verdict] || verdict}
      tone={TONE[verdict] || 'stamp'}
      className={compact ? 'px-1.5 py-0.5 text-[0.5625rem] tracking-[0.12em]' : undefined}
    />
  ) : null;

export default VerdictStamp;
