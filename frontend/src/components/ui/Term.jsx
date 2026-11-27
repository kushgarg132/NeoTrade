import React, { useEffect, useId, useRef } from 'react';
import { Info } from 'lucide-react';
import { GLOSSARY } from '../../utils/glossary';

const GAP = 8;    // px between the icon and the bubble
const EDGE = 16;  // px the bubble keeps from the screen edge

/**
 * A term the product uses that a trader may not read the same way (XIRR, pts vs NIFTY, grade, paper until proven):
 * the label, then an (i) that opens its one-line meaning as a floating bubble under the icon. The bubble is a native
 * popover: it sits above the page (nothing around it moves), and a tap outside, Escape or a scroll closes it. The
 * icon is 16 px; its hit area is 44 px (the ::after inset) without moving the text around it.
 */
const Term = ({ id, children }) => {
  const noteId = useId();
  const btnRef = useRef(null);
  const noteRef = useRef(null);
  const text = GLOSSARY[id];

  useEffect(() => {
    const note = noteRef.current;
    if (!note) return undefined;
    const close = () => note.hidePopover?.();
    const onToggle = (e) => {
      if (e.newState !== 'open') { window.removeEventListener('scroll', close, true); return; }
      // Under the icon, centred on it, kept inside the screen; above it when there is no room below.
      const b = btnRef.current.getBoundingClientRect();
      const n = note.getBoundingClientRect();
      const left = Math.min(Math.max(b.left + b.width / 2 - n.width / 2, EDGE), window.innerWidth - EDGE - n.width);
      const below = b.bottom + GAP;
      note.style.left = `${left}px`;
      note.style.top = `${below + n.height > window.innerHeight - EDGE ? b.top - GAP - n.height : below}px`;
      window.addEventListener('scroll', close, true);
    };
    note.addEventListener('toggle', onToggle);
    return () => { note.removeEventListener('toggle', onToggle); window.removeEventListener('scroll', close, true); };
  }, [text]);

  if (!text) return children;
  return (
    <>
      {children}
      <button ref={btnRef} type="button" popoverTarget={noteId} aria-label={`What ${GLOSSARY_NAME[id] || id} means`}
              onClick={(e) => e.stopPropagation()}
              className="relative ml-1 inline-flex align-[-2px] text-[var(--text-muted)] hover:text-[var(--text)] rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] after:absolute after:-inset-3.5 after:content-['']">
        <Info className="w-4 h-4" aria-hidden="true" />
      </button>
      <span ref={noteRef} id={noteId} popover="auto" role="note"
            className="fixed m-0 inset-auto w-max max-w-[min(20rem,calc(100vw-2rem))] rounded-[12px] border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-left text-[13px] font-normal leading-snug text-[var(--text)] shadow-lg">
        {text}
      </span>
    </>
  );
};

const GLOSSARY_NAME = { xirr: 'XIRR', vsNifty: 'points against NIFTY', grade: 'the grade', paper: 'paper until proven' };

export default Term;
