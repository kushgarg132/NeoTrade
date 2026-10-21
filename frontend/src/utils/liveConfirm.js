// The server's second-tap token (backend/risk/live_confirm.py): single use, 60 s.
// A refused or expired token puts the card back to its first tap; nothing is retried.

export const EXPIRED_NOTE = 'Confirmation expired — tap again';
export const CHANGED_NOTE = 'Order changed — review and tap again';

/**
 * The note to show when a second tap was refused for its token, or null when
 * the error is anything else (a risk check, a network failure): those keep
 * their own handling. Reads the server's `code` (confirm_*); the message-text
 * match below is only a fallback for a backend that predates the codes.
 */
export function tokenRefusal(err) {
  const status = err?.response?.status;
  const { code, detail } = err?.response?.data ?? {};
  if (status !== 409 && status !== 403) return null;
  if (typeof code === 'string' && code.startsWith('confirm_')) {
    if (code === 'confirm_mismatch') return CHANGED_NOTE;
    if (code === 'confirm_other_user') return typeof detail === 'string' ? detail : null;
    return EXPIRED_NOTE; // missing, expired, spent
  }
  if (typeof detail !== 'string') return null;
  if (/different order/i.test(detail)) return CHANGED_NOTE;
  if (/another account/i.test(detail)) return detail;
  if (/confirmation|two taps/i.test(detail)) return EXPIRED_NOTE;
  return null;
}

/** Milliseconds timestamp when a token issued now with `expiresIn` seconds runs out. */
export const deadlineFrom = (expiresIn, now = Date.now()) => now + (Number(expiresIn) > 0 ? Number(expiresIn) : 60) * 1000;

export const secondsLeft = (deadline, now = Date.now()) => Math.max(0, Math.ceil((deadline - now) / 1000));
