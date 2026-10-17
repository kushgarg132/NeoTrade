import logging
from dataclasses import dataclass
from typing import Optional

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from backend.configs.settings import settings

logger = logging.getLogger(__name__)


class InvalidGoogleToken(Exception):
    pass


@dataclass
class GoogleUserInfo:
    sub: str
    email: str
    name: str
    picture: Optional[str] = None


async def verify_google_token(token: str) -> GoogleUserInfo:
    """Verifies a Google ID token's signature, issuer, audience, and expiry
    via Google's own client library (mirrors RoutineOS's use of the Java
    equivalent GoogleIdTokenVerifier -- don't hand-roll JWKS fetching)."""
    try:
        payload = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=settings.GOOGLE_CLIENT_ID,
        )
    except (GoogleAuthError, ValueError) as e:
        logger.warning(f"Google ID token verification failed: {e}")
        raise InvalidGoogleToken(str(e))
    # The email decides the admin role (ADMIN_EMAILS): never trust one Google has not verified.
    if payload.get("email_verified") is False:
        raise InvalidGoogleToken("email not verified")

    return GoogleUserInfo(
        sub=payload["sub"],
        email=payload["email"],
        name=payload.get("name", payload["email"]),
        picture=payload.get("picture"),
    )
