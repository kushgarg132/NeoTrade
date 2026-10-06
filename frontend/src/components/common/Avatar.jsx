import React, { useState } from 'react';

/** Google photo, or the name's first letter when there is none or it fails to load. */
export const Avatar = ({ src, name, size = 40 }) => {
  const [broken, setBroken] = useState(false);
  const style = { width: size, height: size };
  if (src && !broken) {
    return (
      <img
        src={src}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        style={style}
        className="rounded-full object-cover shrink-0 border border-[var(--rule-strong)]"
      />
    );
  }
  return (
    <span
      style={style}
      className="rounded-full shrink-0 grid place-items-center bg-[var(--stamp-soft)] text-[var(--stamp)] font-semibold"
      aria-hidden="true"
    >
      {(name || '?').trim().charAt(0).toUpperCase()}
    </span>
  );
};

