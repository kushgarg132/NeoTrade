import React, { Children, cloneElement, createContext, isValidElement, useContext, useState } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { formatSigned, formatSignedPercent, bareSymbol } from '../../utils/formatters';
import { stockPath } from '../../utils/stocks';

/**
 * The contract note's building blocks. Everything in the app is assembled from
 * these, so a page never invents its own container language.
 */

/** A titled sheet: ruled band, printed title, optional right-hand furniture. */
export const Sheet = ({ title, meta, actions, children, className, bodyClassName }) => (
  <section className={cn('sheet min-w-0', className)}>
    {(title || actions || meta) && (
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2 px-3 py-2 sm:px-4 sm:py-2.5 border-b border-[var(--rule)] bg-[var(--paper-sunk)]">
        <div className="flex items-baseline gap-3 min-w-0">
          {title && <h2 className="field-label text-[var(--ink)] shrink-0">{title}</h2>}
          {meta && <span className="doc-meta truncate min-w-0">{meta}</span>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2 max-w-full">{actions}</div>}
      </header>
    )}
    <div className={cn('p-3 sm:p-4', bodyClassName)}>{children}</div>
  </section>
);

// F&O contracts (NIFTY24OCT25000CE, RELIANCE24OCTFUT) are not in the equity
// instrument master the enquiry reads, so they print but do not link.
const DERIVATIVE = /(\d(CE|PE)|FUT)$/;

// Symbols whose logo 404'd this session, so a re-render or another row does
// not ask again. ponytail: per tab, in memory; persist it if 404s show up in
// the network panel across reloads.
const missingLogos = new Set();

/**
 * A company's logo from FMP's free CDN (NSE listing), lazy-loaded at 20px. The
 * browser caches each image; a symbol with no logo prints its first letter.
 */
export const StockIcon = ({ symbol: raw, className }) => {
  const symbol = bareSymbol(raw)?.toUpperCase();
  const [failed, setFailed] = useState(null);
  if (!symbol) return null;
  const box = 'inline-flex size-5 shrink-0 items-center justify-center border border-[var(--rule)]';
  if (failed === symbol || missingLogos.has(symbol)) {
    return (
      <span aria-hidden="true" className={cn(box, 'bg-[var(--paper-sunk)] text-[0.625rem] font-semibold text-[var(--ink-soft)]', className)}>
        {symbol[0]}
      </span>
    );
  }
  return (
    <img
      src={`https://financialmodelingprep.com/image-stock/${encodeURIComponent(symbol)}.NS.png`}
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

/**
 * A scrip name, wherever it is printed: one tap opens its enquiry on the
 * statement. Stops the click there so a row that is itself clickable (or that
 * expands on click) does not act twice. Equity scrips carry their logo unless
 * `icon={false}`.
 */
export const Scrip = ({ symbol: raw, children, className, icon = true }) => {
  const symbol = bareSymbol(raw);
  const label = children ?? symbol;
  if (!symbol || DERIVATIVE.test(symbol)) {
    return <span className={cn('figure-md', className)}>{label}</span>;
  }
  return (
    <Link
      to={stockPath(symbol)}
      onClick={(event) => event.stopPropagation()}
      className={cn(
        'figure-md underline decoration-[var(--rule)] decoration-1 underline-offset-[3px]',
        'hover:decoration-[var(--stamp)] hover:text-[var(--stamp)] transition-colors',
        icon && 'inline-flex items-center gap-1.5 max-w-full align-middle',
        className
      )}
      aria-label={`Enquire on ${symbol}`}
    >
      {icon ? (
        <>
          <StockIcon symbol={symbol} />
          <span className="min-w-0 truncate">{label}</span>
        </>
      ) : (
        label
      )}
    </Link>
  );
};

/** A field: the label above, the value below, as an official form prints it. */
export const Field = ({ label, value, tone, className }) => (
  <div className={cn('min-w-0', className)}>
    <div className="field-label mb-1">{label}</div>
    <div
      className={cn(
        'figure-md text-sm truncate',
        tone === 'up' && 'text-up',
        tone === 'down' && 'text-down',
        tone === 'stamp' && 'text-[var(--stamp)]'
      )}
    >
      {value}
    </div>
  </div>
);

/**
 * A signed money figure. Sign, colour and magnitude agree; a zero is neither
 * green nor red, because a flat day is not a win.
 */
export const Money = ({ value, className, percent = false, size = 'md' }) => {
  const numeric = Number(value);
  const known = value !== null && value !== undefined && !Number.isNaN(numeric);
  const tone = !known || numeric === 0 ? '' : numeric > 0 ? 'text-up' : 'text-down';
  const text = percent ? formatSignedPercent(value) : formatSigned(value);
  return (
    <span
      className={cn(
        'whitespace-nowrap',
        size === 'lg' ? 'figure-lg' : 'figure-md',
        size === 'md' && 'text-base',
        tone,
        className
      )}
    >
      {known ? text : '—'}
    </span>
  );
};

/**
 * A ruled table. Columns are declared once so every table aligns identically.
 *
 * On a phone the same markup reflows into stacked records (see `.statement` in
 * index.css): the first cell heads the record and every other cell prints under
 * its column's label, so no figure sits behind a sideways swipe.
 */
const ColumnsContext = createContext(null);

export const Statement = ({ columns, children, className, inline = false }) => (
  <div className={cn('sm:overflow-x-auto sm:-mx-4 sm:px-4', className)}>
    <table className={cn('statement w-full border-collapse text-sm', inline && 'statement-inline')}>
      <thead>
        <tr className="border-b border-[var(--rule-strong)]">
          {columns.map((column) => (
            <th
              key={column.key}
              scope="col"
              className={cn(
                'field-label py-2 whitespace-nowrap',
                column.align === 'right' ? 'text-right' : 'text-left'
              )}
            >
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <ColumnsContext.Provider value={columns}>
        <tbody>{children}</tbody>
      </ColumnsContext.Provider>
    </table>
  </div>
);

/** Each cell learns its column's label, which the phone layout prints above it.
 *  A cell may pass its own `data-label` ("" for none) to override that. */
export const Row = ({ children, className, ...props }) => {
  const columns = useContext(ColumnsContext);
  const cells = Children.toArray(children).map((child, index) =>
    isValidElement(child) && columns?.[index]
      ? cloneElement(child, { 'data-label': child.props['data-label'] ?? columns[index].label })
      : child
  );
  return (
    <tr
      className={cn('border-b border-[var(--rule)] last:border-b-0', className)}
      {...props}
    >
      {cells}
    </tr>
  );
};

export const Cell = ({ align, mono, className, children, ...props }) => (
  <td
    className={cn(
      'py-2.5 align-middle',
      align === 'right' ? 'sm:text-right' : 'text-left',
      mono && 'figure-md whitespace-nowrap',
      className
    )}
    {...props}
  >
    {children}
  </td>
);

/** The closing line of a table: a double rule, the way a net is printed. */
export const NetLine = ({ label, children, className }) => (
  <div
    className={cn(
      'rule-net mt-3 pt-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1',
      className
    )}
  >
    <span className="field-label">{label}</span>
    <span className="ml-auto">{children}</span>
  </div>
);

/**
 * The rubber stamp. The one authored motion in this world: a decision lands
 * the way a stamp lands. Used only where something has actually been decided.
 */
export const Stamp = ({ label, tone = 'stamp', animate = false, className }) => {
  const colour =
    tone === 'gain' ? 'var(--gain)' : tone === 'loss' ? 'var(--loss)' : 'var(--stamp)';
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center px-2.5 py-1 border-2 select-none',
        'font-[family-name:var(--font-narrow)] text-[0.6875rem] font-bold uppercase tracking-[0.16em]',
        animate && 'stamp-land',
        className
      )}
      style={{
        color: colour,
        borderColor: colour,
        opacity: 0.85,
        transform: 'rotate(-4deg)',
      }}
    >
      {label}
    </span>
  );
};

export const Empty = ({ title, detail, action, className }) => (
  <div
    className={cn(
      'py-10 px-4 text-center border border-dashed border-[var(--rule)]',
      className
    )}
  >
    <p className="field-label text-[var(--ink)]">{title}</p>
    {detail && (
      <p className="mt-2 text-sm text-[var(--ink-soft)] max-w-sm mx-auto">{detail}</p>
    )}
    {action && <div className="mt-4 flex justify-center">{action}</div>}
  </div>
);

/** Ruled placeholder lines: an unfilled form, not a grey blob. */
export const Ruling = ({ rows = 3, className }) => (
  <div className={cn('space-y-3', className)} aria-hidden="true">
    {Array.from({ length: rows }).map((_, index) => (
      <div key={index} className="h-3 border-b border-[var(--rule)]" />
    ))}
  </div>
);

/**
 * A ruled tab strip: the sections of one long page, so a phone shows one at a
 * time instead of a scroll through all of them. Sticks under the masthead.
 */
export const Tabs = ({ tabs, active, onSelect, label, className }) => (
  <nav
    aria-label={label}
    className={cn(
      'sticky top-[calc(var(--masthead-h)+env(safe-area-inset-top))] z-30 flex overflow-x-auto border-b border-[var(--rule-strong)] bg-[var(--paper)]',
      className
    )}
  >
    {tabs.map((tab) => {
      const selected = tab.id === active;
      return (
        <button
          key={tab.id}
          type="button"
          aria-current={selected ? 'page' : undefined}
          onClick={() => onSelect(tab.id)}
          className={cn(
            // Natural width, never truncated: when the labels outgrow a phone the strip scrolls.
            'flex-1 shrink-0 min-h-11 px-2 inline-flex items-center justify-center gap-1.5 border-b-2 -mb-px whitespace-nowrap transition-colors',
            'font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.08em]',
            selected
              ? 'border-[var(--stamp)] text-[var(--ink)]'
              : 'border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)]'
          )}
        >
          <span>{tab.label}</span>
          {tab.count > 0 && (
            <span className="figure-md px-1 text-[0.5625rem] leading-4 bg-[var(--stamp)] text-[var(--paper)]">
              {tab.count}
            </span>
          )}
        </button>
      );
    })}
  </nav>
);
