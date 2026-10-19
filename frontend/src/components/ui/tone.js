/** Text colour class per tone (gain / loss / warn / neutral). Tokens only. */
export const TONE_TEXT = {
  gain: 'text-[var(--gain)]',
  loss: 'text-[var(--loss)]',
  warn: 'text-[var(--warn)]',
  accent: 'text-[var(--accent)]',
  neutral: 'text-[var(--text)]',
};
export const toneText = (t) => TONE_TEXT[t] || TONE_TEXT.neutral;
