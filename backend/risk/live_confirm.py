"""The server-checked second tap for real money on the user's own account.

The first tap gets a token: random, single use, about a minute long, bound
to the user, the thing being confirmed (a chat card or a proposal) and a
hash of the exact order terms. The tap that places the order must present
it. A client that skips the first tap, replays a token, waits too long or
edits the order between taps places nothing. Every risk check still runs
again at placement; the token only proves a second, deliberate tap.
"""

import hashlib
import json
import secrets
import time

TTL_SECONDS = 60
PREFIX = "live_confirm:"
NEEDS_SECOND_TAP = "Real money. Tap again to send it."
# ponytail: process-local fallback only when Redis is absent (tests); it can
# only refuse more (another process never sees the token), never allow more.
_local: dict[str, tuple[float, str]] = {}


class TokenRefused(Exception):
    """No order: the token is missing, spent, expired, foreign or for other terms."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _binding(user_id: str, subject: str, terms) -> dict:
    digest = hashlib.sha256(json.dumps(terms, sort_keys=True, default=str).encode()).hexdigest()
    return {"user": user_id, "subject": subject, "terms": digest}


async def issue(redis, user_id: str, subject: str, terms) -> str:
    token = secrets.token_urlsafe(8)  # short: it rides in a Telegram button (64 bytes)
    value = json.dumps(_binding(user_id, subject, terms))
    if redis is None:
        _local[token] = (time.monotonic() + TTL_SECONDS, value)
    else:
        await redis.set(PREFIX + token, value, ex=TTL_SECONDS)
    return token


async def redeem(redis, user_id: str, subject: str, terms, token) -> None:
    """Spends the token or raises TokenRefused. Call right before placing."""
    spent = TokenRefused("This confirmation expired or was already used; nothing was sent. Confirm again.")
    if not token or not isinstance(token, str):
        raise TokenRefused("Real money needs two taps: confirm once, then send with the token it returns.")
    if redis is None:
        expires, raw = _local.get(token, (0.0, None))
        raw = raw if expires > time.monotonic() else None
    else:
        raw = await redis.get(PREFIX + token)
    if raw is None:
        raise spent
    stored = json.loads(raw)
    if stored.get("user") != user_id:
        raise TokenRefused("This confirmation belongs to another account.", status=403)
    # The owner presented it: it is spent whatever happens next, and only
    # one of two racing taps gets to spend it.
    gone = (_local.pop(token, None) is not None) if redis is None else (await redis.delete(PREFIX + token)) == 1
    if not gone:
        raise spent
    if stored != _binding(user_id, subject, terms):
        raise TokenRefused("This confirmation was for a different order; nothing was sent. Confirm again.")
