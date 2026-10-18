"""Kite Connect login-token lifecycle: the human-in-the-loop OAuth-style flow
Kite documents at https://kite.trade/docs/connect/v3/user/#login-flow, plus
daily token expiry (~06:00 IST, Kite's documented behavior, not a fixed TTL).

Real pykiteconnect (5.x) API surface this maps to (verified against the
installed package's source, not just docs, since no live account exists to
hit the real endpoints in this session):

- `KiteConnect(api_key=...).login_url()` -> builds and returns the documented
  login redirect URL. In pykiteconnect 5.2.1 this is literally
  `f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"`
  (connect.py: `_default_login_uri = "https://kite.zerodha.com/connect/login"`).
  We call the SDK's own method rather than hardcoding this string ourselves
  -- if Kite ever changes the host/query shape, this code doesn't need to
  change with it.
- `KiteConnect(api_key=...).generate_session(request_token, api_secret)` ->
  POST to Kite's `api.token` route (https://api.kite.trade/session/token).
  The SDK computes the documented `SHA-256(api_key + request_token +
  api_secret)` checksum internally; this file never reimplements that
  HMAC/hash logic itself, per the task brief. Returns a dict containing
  `access_token` (plus user/session metadata we don't need here).
- `KiteConnect(api_key=..., access_token=...).profile()` -> GET
  https://api.kite.trade/user/profile (`user.profile`). Used here only as a
  cheap probe to validate a cached access_token: Kite's documented
  `TokenException` (HTTP 403, `error_type: "TokenException"`) is how the API
  reports an expired/invalidated session, which is exactly the
  ACTIVE/DEGRADED signal this module needs.

`KiteConnect` is patched at the class level in every test -- nothing here
ever makes a real HTTP call.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo

from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException

_IST = ZoneInfo("Asia/Kolkata")


def _redis_key(user_id: str) -> str:
    """One cached token per user per broker. This was a single fixed key
    until 2026-09-09, which meant whoever connected last was trading for
    everyone signed in."""
    return f"broker:{user_id}:kite:access_token"


class KiteSessionState(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"  # no API key/secret in settings at all
    NEEDS_LOGIN = "NEEDS_LOGIN"  # key/secret present, no valid access_token
    ACTIVE = "ACTIVE"  # valid, unexpired access_token
    DEGRADED = "DEGRADED"  # access_token present but rejected/expired by Kite


def next_6am_ist(now_utc: datetime) -> datetime:
    """Kite access tokens expire daily at ~06:00 IST. Returns the next such
    instant strictly after `now_utc`, as a UTC datetime (for a Redis TTL,
    which only understands seconds, not timezones)."""
    now_ist = now_utc.astimezone(_IST)
    candidate_ist = now_ist.replace(hour=6, minute=0, second=0, microsecond=0)
    if now_ist >= candidate_ist:
        candidate_ist += timedelta(days=1)
    return candidate_ist.astimezone(timezone.utc)


class KiteSessionManager:
    def __init__(
        self, api_key: Optional[str], api_secret: Optional[str], redis, user_id: str
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._redis = redis
        self._key = _redis_key(user_id)

    def _client(self, access_token: Optional[str] = None) -> KiteConnect:
        return KiteConnect(api_key=self._api_key, access_token=access_token)

    async def state(self) -> KiteSessionState:
        if not self._api_key or not self._api_secret:
            return KiteSessionState.UNCONFIGURED

        token = await self.get_access_token()
        if not token:
            return KiteSessionState.NEEDS_LOGIN

        try:
            await asyncio.to_thread(self._client(token).profile)
        except TokenException:
            return KiteSessionState.DEGRADED
        return KiteSessionState.ACTIVE

    async def generate_login_url(self) -> str:
        """Returns the Kite login URL a human should visit. Raises when
        UNCONFIGURED -- there is no api_key to build a URL from."""
        if not self._api_key:
            raise RuntimeError("Cannot generate Kite login URL: no Kite API key is set (broker credentials are per-user)")
        return self._client().login_url()

    async def exchange_request_token(self, request_token: str) -> str:
        """Exchanges a request_token (obtained by a human completing the
        login flow and Kite redirecting back with it in the query string)
        for an access_token via the SDK's generate_session, then caches it
        in Redis with an expiry set to the next 06:00 IST."""
        if not self._api_key or not self._api_secret:
            raise RuntimeError("Cannot exchange Kite request_token: no Kite API key/secret is set (broker credentials are per-user)")

        session = await asyncio.to_thread(self._client().generate_session, request_token, self._api_secret)
        access_token = session["access_token"]

        now = datetime.now(timezone.utc)
        ttl_seconds = max(1, int((next_6am_ist(now) - now).total_seconds()))
        await self._redis.set(self._key, access_token, ex=ttl_seconds)
        return access_token

    async def get_access_token(self) -> Optional[str]:
        return await self._redis.get(self._key)

    async def clear(self) -> None:
        """Forgets the cached access token. Kite has no logout endpoint, so
        disconnecting means dropping our copy; the token stays valid on
        Kite's side until it expires at 06:00 IST."""
        await self._redis.delete(self._key)
