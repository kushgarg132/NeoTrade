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

export const formatClock = (value) => {
  if (!value) return '—';
  return new Intl.DateTimeFormat('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
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
