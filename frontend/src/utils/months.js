/** Calendar-month keys ("2026-09") shared by the journal and the paper scorecard. */

export const monthKey = (day) => day.slice(0, 7);

export const shiftMonth = (key, delta) => {
  const [year, month] = key.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1 + delta, 1));
  return date.toISOString().slice(0, 7);
};

export const monthLabel = (key, month = 'long') =>
  new Intl.DateTimeFormat('en-IN', { month, year: 'numeric', timeZone: 'UTC' }).format(
    new Date(`${key}-01T00:00:00Z`)
  );

export const todayIst = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
