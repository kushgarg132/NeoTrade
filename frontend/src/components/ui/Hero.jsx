import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { inr } from './format';

const reduced = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/**
 * The big number on a glow surface. Counts up 0 -> value once, on first mount; a later change renders directly.
 * `anim` is the in-flight number, null once settled, so the settled text is always exactly format(value).
 */
const Hero = ({ label, value, format = inr, change, children, to, privateValue = true }) => {
  const [anim, setAnim] = useState(() => (reduced() || typeof value !== 'number' ? null : 0));
  const target = useRef(value);
  target.current = value;
  useEffect(() => {
    if (anim === null) return undefined;
    let raf;
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min((now - t0) / 600, 1);
      if (p >= 1) { setAnim(null); return; }
      setAnim(target.current * (1 - (1 - p) ** 3));
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only: later value changes must not re-animate
  }, []);
  const body = (
    <>
      <div className="text-[13px] font-medium text-[var(--text-muted)]">{label}</div>
      <div className={`${privateValue ? 'private ' : ''}figure-md hero-num mt-2 text-[var(--text)]`}>{format(anim === null ? value : anim)}</div>
      {change && <div className="mt-2">{change}</div>}
      {children}
    </>
  );
  const cls = 'block rounded-[28px] border border-[var(--border)] p-5';
  const style = { background: 'var(--glow)' };
  return to
    ? <Link to={to} className={`${cls} tap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`} style={style}>{body}</Link>
    : <div className={cls} style={style}>{body}</div>;
};

export default Hero;
