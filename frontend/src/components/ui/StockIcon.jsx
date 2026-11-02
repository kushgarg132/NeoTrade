import React, { useState } from 'react';
import { cn } from '../../utils/cn';
import { bareSymbol } from '../../utils/formatters';
import { isDerivative, logoUrl } from '../../utils/stocks';

// Symbols whose logo 404'd this session, so a re-render or another row does
// not ask again. Across reloads the browser keeps the 404 for a day
// (Nginx's Cache-Control on /logo/).
const missingLogos = new Set();

/**
 * A company's logo (`utils/stocks.js::logoUrl`), lazy-loaded, 20px unless `className` sizes it. The browser keeps
 * each image 30 days. A symbol with no logo, or an F&O contract, prints its first letter without asking.
 */
const StockIcon = ({ symbol: raw, className }) => {
  const symbol = bareSymbol(raw)?.toUpperCase();
  const [failed, setFailed] = useState(null);
  if (!symbol) return null;
  const box = 'inline-flex size-5 shrink-0 items-center justify-center rounded-[6px] border border-[var(--border)]';
  if (failed === symbol || missingLogos.has(symbol) || isDerivative(symbol)) {
    return (
      <span aria-hidden="true" className={cn(box, 'bg-[var(--surface-2)] text-[12px] font-semibold text-[var(--text-muted)]', className)}>
        {symbol[0]}
      </span>
    );
  }
  return (
    <img
      src={logoUrl(symbol)}
      alt=""
      width={20}
      height={20}
      loading="lazy"
      decoding="async"
      onError={() => {
        missingLogos.add(symbol);
        setFailed(symbol);
      }}
      className={cn(box, 'bg-white object-contain p-px', className)}
    />
  );
};

export default StockIcon;
