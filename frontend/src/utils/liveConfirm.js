// The server's second-tap token (backend/risk/live_confirm.py): single use, 60 s.
// A refused or expired token puts the card back to its first tap; nothing is retried.

export const EXPIRED_NOTE = 'Confirmation expired — tap again';
export const CHANGED_NOTE = 'Order changed — review and tap again';

/**
 * The note to show when a second tap was refused for its token, or null when
 * the error is anything else (a risk check, a network failure): those keep
 * their own handling. Matches the messages TokenRefused carries.
 */
export function tokenRefusal(err) {
  const status = err?.response?.status;
  const detail = err?.response?.data?.detail;
  if ((status !== 409 && status !== 403) || typeof detail !== 'string') return null;
  if (/different order/i.test(detail)) return CHANGED_NOTE;
  if (/another account/i.test(detail)) return detail;
  if (/confirmation|two taps/i.test(detail)) return EXPIRED_NOTE;
  return null;
}

/** Milliseconds timestamp when a token issued now with `expiresIn` seconds runs out. */
export const deadlineFrom = (expiresIn, now = Date.now()) => now + (Number(expiresIn) > 0 ? Number(expiresIn) : 60) * 1000;

export const secondsLeft = (deadline, now = Date.now()) => Math.max(0, Math.ceil((deadline - now) / 1000));
