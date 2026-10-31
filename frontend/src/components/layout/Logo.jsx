import React from 'react';

/**
 * The NeoTrade mark: two halves interlock into one N. The left half (your account) takes the
 * text colour; the right half (the AI account) is always the brand emerald, never the section
 * accent. Same geometry as `public/icon.svg`.
 */
export const LogoMark = ({ size = 24, className }) => (
  <svg width={size} height={size} viewBox="20 20 60 60" className={className} aria-hidden="true">
    <polygon points="26,76 26,24 40,24 53.54,44.7 43.73,51.11 40,45.41 40,76" fill="currentColor" />
    <polygon points="74,24 74,76 60,76 46.46,55.3 56.27,48.89 60,54.59 60,24" fill="#10b981" />
  </svg>
);

/** Mark + wordmark, as the masthead shows it. */
const Logo = ({ className }) => (
  <span className={`inline-flex items-center gap-2 text-[18px] font-bold text-[var(--text)] ${className || ''}`}>
    <LogoMark size={22} />
    NeoTrade
  </span>
);

export default Logo;
