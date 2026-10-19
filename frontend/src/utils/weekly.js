// ISO week ids ("2026-W42") for the weekly report's prev/next buttons. Pure.
const monday = (id) => {
  const [y, w] = id.split('-W').map(Number);
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const d = new Date(jan4.getTime() + ((w - 1) * 7 - ((jan4.getUTCDay() + 6) % 7)) * 86400000);
  return d;
};

/** shiftWeek("2026-W42", -1) = "2026-W41"; crosses year ends. */
export const shiftWeek = (id, by) => {
  const d = new Date(monday(id).getTime() + by * 7 * 86400000);
  const thu = new Date(d.getTime() + 3 * 86400000); // the ISO year is the Thursday's
  const y = thu.getUTCFullYear();
  const w = Math.floor((thu - Date.UTC(y, 0, 1)) / 86400000 / 7) + 1;
  return `${y}-W${String(w).padStart(2, '0')}`;
};

/** "12 Oct - 18 Oct" for the week's Monday to Sunday. */
export const weekRange = (id) => {
  const f = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const m = monday(id);
  return `${f(m)} - ${f(new Date(m.getTime() + 6 * 86400000))}`;
};
