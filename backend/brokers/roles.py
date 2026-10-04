"""Which broker account is for what. A user may give one connected broker
the `ai` role (the autopilot trades it, backend/autopilot/) and any others
`mine` (the user trades; the AI only proposes cards). Orders are routed by
role -- never to "whichever broker happens to be logged in" -- so an AI
order can't reach the user's own account, and vice versa."""

from typing import Literal, Optional

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, get_broker_adapter

Role = Literal["ai", "mine"]
ROLES = ("ai", "mine")
LABELS = {"ai": "The AI account", "mine": "Your account"}


class RoleUnavailable(Exception):
    def __init__(self, role: str, reason: str):
        super().__init__(reason)
        self.role, self.reason = role, reason


def validate_roles(roles: dict) -> dict:
    for broker, role in roles.items():
        if broker not in BROKERS:
            raise ValueError(f"Unknown broker {broker!r}. Known: {', '.join(sorted(BROKERS))}")
        if role not in ROLES:
            raise ValueError(f"A broker's role is 'ai' or 'mine', not {role!r}")
    if sum(role == "ai" for role in roles.values()) > 1:
        raise ValueError("Only one broker can be the AI account")
    return dict(roles)


def brokers_for(roles: dict, role: str) -> set[str]:
    return {broker for broker, r in (roles or {}).items() if r == role}


async def adapter_for(user_id: str, role: Role, credentials, redis=None, roles: Optional[dict] = None,
                      get_adapter=None):
    """The adapter of the broker holding `role`, logged in -- or RoleUnavailable.
    Never another broker's: no fallback across roles."""
    if roles is None:
        from backend.database import db
        from backend.prefs import PrefsStore

        roles = (await PrefsStore(db.db).get(user_id)).get("broker_roles") or {}
        redis = redis if redis is not None else db.redis
    brokers = sorted(brokers_for(roles, role))
    if not brokers:
        raise RoleUnavailable(role, f"{LABELS[role]} is not set: choose it in Settings → Broker.")
    for broker in brokers:
        adapter = await (get_adapter or get_broker_adapter)(broker, user_id, credentials, redis)
        if await adapter.state() == BrokerSessionState.ACTIVE:
            return adapter
    raise RoleUnavailable(role, f"{LABELS[role]} ({', '.join(b.title() for b in brokers)}) is not logged in today.")
