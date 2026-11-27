import React from 'react';
import { px } from './levels';

/** Where `x` sits between lo and hi, in percent, kept on the track. */
const at = (x, lo, hi) => (hi > lo ? Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100)) : 50);

/**
 * The trade plan on one price line: the stop, the buy zone and the target, with today's price as a marker. Loss tint
 * from the stop to the zone, the section accent over the zone, gain tint from the zone to the target. The labels sit
 * in a row under the line (never on it), so they cannot collide. Nothing to draw without a stop and a target.
 */
const LevelsLine = ({ stop, zone, entry, target, now }) => {
  const lo0 = zone?.[0] ?? entry;
  const hi0 = zone?.[1] ?? entry;
  if (stop == null || target == null || lo0 == null) return null;
  const lo = Math.min(stop, now ?? stop);
  const hi = Math.max(target, now ?? target);
  const s = at(stop, lo, hi);
  const z0 = at(lo0, lo, hi);
  const z1 = Math.max(at(hi0, lo, hi), z0 + 1.5); // a one-price zone still shows
  const t = at(target, lo, hi);
  const n = now != null ? at(now, lo, hi) : null;
  const nowTone = now == null ? '' : now < stop ? 'text-[var(--loss)]' : now > hi0 ? 'text-[var(--text)]' : 'text-[var(--gain)]';
  return (
    <figure className="m-0">
      <div className="relative h-14" role="img"
        aria-label={`Stop ${px(stop)}, buy ${zone ? `${px(zone[0])} to ${px(zone[1])}` : `at ${px(entry)}`}, target ${px(target)}${now != null ? `, now ${px(now)}` : ''}`}>
        {n != null && (
          <div className="absolute top-0 -translate-x-1/2 flex flex-col items-center" style={{ left: `${Math.min(Math.max(n, 8), 92)}%` }}>
            <span className={`whitespace-nowrap text-[12px] font-semibold tabular-nums ${nowTone}`}>Now {px(now)}</span>
          </div>
        )}
        {n != null && <div className="absolute top-[18px] h-[22px] w-0.5 -translate-x-1/2 rounded-full bg-[var(--text)]" style={{ left: `${n}%` }} />}
        <div className="absolute inset-x-0 top-[26px] h-2 rounded-full bg-[var(--surface-2)]" />
        <div className="absolute top-[26px] h-2 rounded-l-full bg-[var(--loss-soft)]" style={{ left: `${s}%`, width: `${Math.max(z0 - s, 0)}%` }} />
        <div className="absolute top-[26px] h-2 bg-[var(--accent)]" style={{ left: `${z0}%`, width: `${z1 - z0}%` }} />
        <div className="absolute top-[26px] h-2 rounded-r-full bg-[var(--gain-soft)]" style={{ left: `${z1}%`, width: `${Math.max(t - z1, 0)}%` }} />
        <div className="absolute top-[22px] h-4 w-0.5 -translate-x-1/2 rounded-full bg-[var(--loss)]" style={{ left: `${s}%` }} />
        <div className="absolute top-[22px] h-4 w-0.5 -translate-x-1/2 rounded-full bg-[var(--gain)]" style={{ left: `${t}%` }} />
      </div>
      <figcaption className="grid grid-cols-3 gap-2 text-[13px] tabular-nums">
        <span><span className="block text-[var(--text-muted)]">Stop</span><span className="font-semibold text-[var(--loss)]">{px(stop)}</span></span>
        <span className="text-center"><span className="block text-[var(--text-muted)]">{zone ? 'Buy up to' : 'Entry'}</span><span className="font-semibold text-[var(--text)]">{px(zone ? zone[1] : entry)}</span></span>
        <span className="text-right"><span className="block text-[var(--text-muted)]">Target</span><span className="font-semibold text-[var(--gain)]">{px(target)}</span></span>
      </figcaption>
    </figure>
  );
};

export default LevelsLine;
