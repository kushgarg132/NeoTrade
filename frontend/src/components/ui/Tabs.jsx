import React, { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/** Arrow keys, Home and End move between tabs (WAI-ARIA tabs, selection follows focus); only the chosen tab is in the Tab order. */
const onKeys = (e, tabs, value, onChange) => {
  const i = tabs.findIndex((t) => t.id === value);
  const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  const next = tabs[(to + tabs.length) % tabs.length];
  onChange(next.id);
  e.currentTarget.querySelector(`[data-tab="${next.id}"]`)?.focus();
};

/** Segmented, scrollable tab strip (`wrap`: wraps to rows instead of scrolling). `tabs: [{id, label, badge?}]`. */
const Tabs = ({ tabs, value, onChange, label = 'Tabs', wrap = false }) => (
  <div role="tablist" aria-label={label} onKeyDown={(e) => onKeys(e, tabs, value, onChange)} className={`flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1 ${wrap ? 'flex-wrap' : 'overflow-x-auto'}`}>
    {tabs.map((t) => {
      const on = t.id === value;
      return (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={on}
          tabIndex={on ? 0 : -1}
          data-tab={t.id}
          onClick={() => onChange(t.id)}
          className={`${wrap ? 'basis-[22%]' : 'shrink-0'} flex-1 min-h-11 px-3 rounded-[8px] text-[14px] font-medium whitespace-nowrap inline-flex items-center justify-center gap-1.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
            on ? 'bg-[var(--surface)] text-[var(--text)] fade-in' : 'text-[var(--text-muted)]'
          }`}
        >
          {t.label}
          {t.badge > 0 && (
            <span className="min-w-5 px-1 rounded-full bg-[var(--accent)] text-[var(--accent-ink)] text-[12px] leading-5 text-center tabular-nums">
              {t.badge}
            </span>
          )}
        </button>
      );
    })}
  </div>
);

/** URL-backed tab state: `?tab=<id>`, the default id leaves the URL clean. Unknown ids fall back to the default. */
// eslint-disable-next-line react-refresh/only-export-components
export const useTabParam = (ids, defaultId = ids[0], key = 'tab', alias = (x) => x) => {
  const [params, setParams] = useSearchParams();
  const raw = alias(params.get(key));
  const tab = ids.includes(raw) ? raw : defaultId;
  const setTab = useCallback(
    (id) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id === defaultId) next.delete(key);
          else next.set(key, id);
          return next;
        },
        { replace: true },
      ),
    [setParams, defaultId, key],
  );
  return [tab, setTab];
};

export default Tabs;
