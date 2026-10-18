/** Used until GET /system/schedule loads (or if it fails); mirrors the backend constants. */
export const FALLBACK_SCHEDULE = {
  daily_pass: '16:00', plan: '08:45', session_open: '09:15', session_close: '15:30', square_off: '15:15',
  morning: '09:20', monitor_open: '09:15', monitor_close: '15:35', exit_check_minutes: 15,
};

/** "16:00" -> "4:00 PM". */
export const clock12 = (hhmm) => {
  const [h, m] = hhmm.split(':').map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
};

/** Payload -> 12-hour strings for its "HH:MM" fields. */
export const clockTimes = (raw) => Object.fromEntries(
  Object.entries(raw).filter(([, v]) => typeof v === 'string').map(([k, v]) => [k, clock12(v)])
);
