import React from 'react';
import Card from '../ui/Card';
import { toneText } from '../ui/tone';
import { heatColor } from '../ui/chartTheme';
import { techSummary } from '../../utils/stock';

const READ = { bull: ['Bullish', 'gain'], bear: ['Bearish', 'loss'], neutral: ['Neutral', 'neutral'] };

/** Technical summary as a gauge: bearish | neutral | bullish segments sized by count, plus the readings. A count, not advice. */
const TechGauge = ({ t }) => {
  const s = techSummary(t);
  if (!s) return null;
  const n = s.rows.length;
  const seg = [
    ['Bearish', s.bear, heatColor(-3)],
    ['Neutral', s.neutral, heatColor(0)],
    ['Bullish', s.bull, heatColor(3)],
  ];
  return (
    <Card title="Technical summary">
      <p className={`text-[17px] font-semibold ${toneText(s.tone)}`}>{s.label}</p>
      <div className="mt-2 flex h-3 gap-0.5 rounded-full overflow-hidden" role="img" aria-label={`${s.bear} bearish, ${s.neutral} neutral, ${s.bull} bullish of ${n} indicators`}>
        {seg.map(([name, count, color]) => count > 0 && <div key={name} style={{ flex: count, background: color }} />)}
      </div>
      <div className="mt-1 flex justify-between text-[13px] tabular-nums text-[var(--text-muted)]">
        <span>{s.bear} bearish</span><span>{s.neutral} neutral</span><span>{s.bull} bullish</span>
      </div>
      <ul className="mt-3">
        {s.rows.map((r) => (
          <li key={r.name} className="flex justify-between min-h-9 items-center border-t border-[var(--border)] text-[14px]">
            <span className="text-[var(--text-muted)]">{r.name}</span>
            <span className={`font-semibold ${toneText(READ[r.read][1])}`}>{READ[r.read][0]}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12px] text-[var(--text-muted)]">Daily bars. A count of indicator readings, not advice.</p>
    </Card>
  );
};

export default TechGauge;
