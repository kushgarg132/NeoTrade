import React from 'react';
import { Link } from 'react-router-dom';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { formatCompactNumber } from '../../utils/formatters';
import { stockPath } from '../../utils/stocks';

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const PERIODS = [['1w', '1W'], ['1m', '1M'], ['3m', '3M'], ['6m', '6M'], ['1y', '1Y']];

/**
 * What the stock is and how it has been doing, for any stock: sector and industry, returns over 1W to 1Y (from
 * quick-analyze `technical_analysis.returns`, percent units), the last session's volume against its average, and
 * peers when the backend has them. Nothing renders when none of it is known.
 */
const MarketFacts = ({ quick }) => {
  const c = quick?.company_info || {};
  const r = quick?.technical_analysis?.returns || {};
  const rets = PERIODS.filter(([k]) => isNum(r[k]));
  const peers = (quick?.peers || []).map((p) => (typeof p === 'string' ? p : p?.symbol)).filter(Boolean).slice(0, 6);
  const where = [c.sector, c.industry].filter(Boolean).join(' · ');
  const vol = isNum(c.volume) && isNum(c.avg_volume) && c.avg_volume > 0 ? c.volume / c.avg_volume : null;
  if (!rets.length && !where && vol == null && !peers.length) return null;
  return (
    <section aria-label="How it has done" className="mb-3 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
      {(where || vol != null) && (
        <p className="text-[13px] text-[var(--text-muted)]">
          {where}
          {where && vol != null && ' · '}
          {vol != null && <>Volume {formatCompactNumber(c.volume)}, <span className={vol >= 1.5 ? 'font-semibold text-[var(--text)]' : ''}>{vol.toFixed(1)}× its average</span></>}
        </p>
      )}
      {rets.length > 0 && (
        <dl className={`grid grid-cols-5 gap-2 ${where || vol != null ? 'mt-2' : ''}`}>
          {rets.map(([k, label]) => (
            <div key={k} className="min-w-0 rounded-[12px] bg-[var(--surface-2)] px-2 py-1.5 text-center">
              <dt className="text-[12px] text-[var(--text-muted)]">{label}</dt>
              <dd className={`text-[14px] font-semibold tabular-nums ${toneText(tone(r[k]))}`}>{pct(r[k] / 100, { sign: true, dp: 1 })}</dd>
            </div>
          ))}
        </dl>
      )}
      {peers.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-1.5 text-[13px]">
          <span className="text-[var(--text-muted)]">Peers</span>
          {peers.map((p) => (
            <Link key={p} to={stockPath(p)} className="tap inline-flex min-h-11 items-center">
              <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[12px] font-medium text-[var(--text)]">{p.replace(/\.(NS|BO)$/i, '')}</span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
};

export default MarketFacts;
