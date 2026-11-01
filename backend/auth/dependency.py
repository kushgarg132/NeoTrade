from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.auth.jwt import decode_session_jwt, InvalidSessionToken
from backend.auth.models import User
from backend.auth.store import UserStore
from backend.database import db

_bearer_scheme = HTTPBearer()
_optional_bearer = HTTPBearer(auto_error=False)


async def get_user_store() -> UserStore:
    return UserStore(db.db)


async def _resolve_user(token: str, user_store: UserStore) -> User:
    try:
        user_id = decode_session_jwt(token)
    except InvalidSessionToken:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    user = await user_store.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    user_store: UserStore = Depends(get_user_store),
) -> User:
    return await _resolve_user(credentials.credentials, user_store)


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    user_store: UserStore = Depends(get_user_store),
) -> Optional[User]:
    """Public routes: no credentials -> guest (None); bad credentials -> 401."""
    if credentials is None:
        return None
    return await _resolve_user(credentials.credentials, user_store)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Gate for deployment-wide settings, which are shared by every user and
    so must not be writable by merely being signed in."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
