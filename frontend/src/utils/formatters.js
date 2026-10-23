/** This is an NSE product: rupees and Indian digit grouping are the default. */

export const formatCurrency = (value, currency = 'INR') => {
  if (value === null || value === undefined || isNaN(value)) return '—';
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
};

/** A net always carries its sign: a statement never leaves the reader guessing. */
export const formatSigned = (value, currency = 'INR') => {
  if (value === null || value === undefined || isNaN(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return sign + formatCurrency(Math.abs(value), currency);
};

export const formatQuantity = (value) => {
  if (value === null || value === undefined || isNaN(value)) return '—';
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(value);
};

export const formatCompactNumber = (value) => {
  if (value === null || value === undefined || isNaN(value)) return '—';
  return new Intl.NumberFormat('en-IN', {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value);
};

export const formatPercent = (value) => {
  if (value === null || value === undefined || isNaN(value)) return '—';
  return new Intl.NumberFormat('en-IN', {
    style: 'percent',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value / 100);
};

export const formatSignedPercent = (value) => {
  if (value === null || value === undefined || isNaN(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return sign + formatPercent(Math.abs(value));
};

/** Document furniture: the date a note is issued under. */
export const formatNoteDate = (date = new Date()) =>
  new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata',
  })
    .format(date)
    .toUpperCase();

/** Every clock time in the app: 12-hour IST, "3:20 PM". */
export const formatClock = (value) => {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'Asia/Kolkata',
  }).format(new Date(value));
};

export const formatDateTime = (value) => {
  if (!value) return '—';
  return `${formatNoteDate(new Date(value))} ${formatClock(value)}`;
};

export const formatTimeAgo = (dateString) => {
  if (!dateString) return '';
  const seconds = Math.floor((Date.now() - new Date(dateString)) / 1000);
  if (seconds < 60) return 'just now';
  const steps = [
    [31536000, 'y'],
    [2592000, 'mo'],
    [86400, 'd'],
    [3600, 'h'],
    [60, 'm'],
  ];
  for (const [span, unit] of steps) {
    if (seconds >= span) return `${Math.floor(seconds / span)}${unit} ago`;
  }
  return 'just now';
};

/**
 * The NSE session in IST: pre-open 09:00–09:15, open 09:15–15:30, weekdays. Holidays are not modelled —
 * on one the app says "closed" a few hours late, which is a smaller lie than
 * showing a frozen tick as live.
 */
export const marketPhase = (now = new Date()) => {
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }));
  const day = ist.getDay();
  if (day === 0 || day === 6) return 'closed';
  const minutes = ist.getHours() * 60 + ist.getMinutes();
  if (minutes < 540) return 'closed'; // overnight, before the 09:00 pre-open
  if (minutes < 555) return 'pre';
  if (minutes >= 930) return 'closed';
  return 'open';
};

const LIVE = new Set(['open', 'pre', 'session']); // marketPhase() and GET /today `phase` both
const STALE_LIVE_MS = 15 * 60_000;
const STALE_CLOSED_MS = 4 * 86_400_000; // a long weekend plus a day

/** A failed refresh, for a tile that keeps its last figure on screen. */
export const REFRESH_FAILED = { text: "Couldn't refresh", stale: true };

/**
 * The freshness line under a market figure: `at` is epoch seconds, ms or an ISO string,
 * `phase` either marketPhase() or /today's. In session "as of 2:31 PM", stale past 15 min;
 * closed "Market closed · last close", or the date once it is older than a long weekend.
 * null when there is no `at`.
 */
export const asOf = (at, phase = marketPhase(), now = Date.now()) => {
  if (at === null || at === undefined || at === '') return null;
  const ms = typeof at === 'number' ? (at < 1e12 ? at * 1000 : at) : new Date(at).getTime();
  if (!Number.isFinite(ms)) return null;
  const age = now - ms;
  if (LIVE.has(phase)) {
    const stale = age > STALE_LIVE_MS;
    return { text: `${stale ? 'Stale · ' : ''}as of ${formatClock(ms)}`, stale };
  }
  return age > STALE_CLOSED_MS
    ? { text: `Stale · as of ${formatDateTime(ms)}`, stale: true }
    : { text: 'Market closed · last close', stale: false };
};

/** Index levels are points, not rupees: grouped, two decimals, no symbol. */
export const formatLevel = (value) => {
  if (value === null || value === undefined || isNaN(value)) return '—';
  return new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
};

/**
 * Yahoo-sourced lists (the day's movers) name NSE/BSE scrip as "AXISBANK.NS";
 * the instrument master and every other screen use the bare symbol.
 */
export const bareSymbol = (symbol) => (symbol ? symbol.replace(/\.(NS|BO)$/i, '') : symbol);
