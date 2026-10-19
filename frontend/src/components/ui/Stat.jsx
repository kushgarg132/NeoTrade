import React from 'react';
import { toneText } from './tone';

/** A label over a figure, with an optional delta line in `tone`. */
const Stat = ({ label, value, delta, tone = 'neutral' }) => (
  <div className="min-w-0">
    <div className="text-[13px] text-[var(--text-muted)]">{label}</div>
    <div className="private figure-md text-[17px] font-semibold tabular-nums text-[var(--text)] truncate">{value}</div>
    {delta != null && <div className={`text-[13px] tabular-nums ${toneText(tone)}`}>{delta}</div>}
  </div>
);

export default Stat;
