import React, { useId, useState } from 'react';
import { Info } from 'lucide-react';
import { GLOSSARY } from '../../utils/glossary';

/**
 * A term the product uses that a trader may not read the same way (XIRR, pts vs NIFTY, grade, paper until proven):
 * the label, then an (i) that opens its one-line meaning in place. Tap again, or Escape, closes it. The icon is 16 px;
 * its hit area is 44 px (the ::after inset) without moving the text around it.
 */
const Term = ({ id, children }) => {
  const [open, setOpen] = useState(false);
  const noteId = useId();
  const text = GLOSSARY[id];
  if (!text) return children;
  return (
    <>
      {children}
      <button type="button" aria-expanded={open} aria-controls={noteId} aria-label={`What ${GLOSSARY_NAME[id] || id} means`}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((v) => !v); }}
              onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
              className="relative ml-1 inline-flex align-[-2px] text-[var(--text-muted)] hover:text-[var(--text)] rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] after:absolute after:-inset-3.5 after:content-['']">
        <Info className="w-4 h-4" aria-hidden="true" />
      </button>
      {open && (
        <span id={noteId} role="note" className="mt-1.5 block max-w-prose rounded-[12px] bg-[var(--surface-2)] px-3 py-2 text-[13px] font-normal leading-snug text-[var(--text)]">
          {text}
        </span>
      )}
    </>
  );
};

const GLOSSARY_NAME = { xirr: 'XIRR', vsNifty: 'points against NIFTY', grade: 'the grade', paper: 'paper until proven' };

export default Term;
