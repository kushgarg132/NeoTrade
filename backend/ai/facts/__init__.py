"""The fact layer: the one read-only path AI features use to see data.

Every fact is `async def fact(db, redis, user_id, **args) -> dict` and its
result always carries `as_of` (ISO UTC) and `source`. A failed read returns
`{"error": ..., "as_of": ...}` -- it never raises, so a model can say
"unavailable" instead of guessing. User facts filter by `user_id`; market
facts ignore it. `as_tools` exposes facts to a model as LangChain tools
(docs/superpowers/specs/2026-10-06-ai-tools-fact-layer-design.md).
"""

import functools
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)
CONTEXT_PARAMS = ("db", "redis", "user_id")


@dataclass(frozen=True)
class Fact:
    name: str
    fn: Callable
    description: str
    user: bool


FACTS: dict[str, Fact] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fact(name: str, description: str, user: bool = False, source: str = ""):
    """Registers a fact; the wrapper adds as_of/source and turns any error into data."""
    def register(fn):
        @functools.wraps(fn)
        async def wrapped(db, redis, user_id, **args):
            try:
                out = await fn(db, redis, user_id, **args)
            except Exception as exc:
                logger.warning("fact %s failed: %s", name, exc)
                out = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            return {"as_of": now_iso(), "source": source or name, **out}
        FACTS[name] = Fact(name, wrapped, description, user)
        return wrapped
    return register


def as_tools(db, redis, user_id: Optional[str], names: list[str]) -> list[StructuredTool]:
    """The named facts as tools bound to this call's db, redis and user."""
    from backend.ai.facts import market, user  # noqa: F401  (registers)

    tools = []
    for name in names:
        spec = FACTS[name]
        if spec.user and not user_id:
            # {"user_id": None} would match legacy rows with no owner.
            raise ValueError(f"fact {name} needs a user")
        signature = inspect.signature(spec.fn)
        params = [p for n, p in signature.parameters.items() if n not in CONTEXT_PARAMS]

        async def call(_spec=spec, **args):
            return json.dumps(await _spec.fn(db, redis, user_id, **args), default=str, ensure_ascii=False)

        call.__signature__ = signature.replace(parameters=params)
        call.__annotations__ = {k: v for k, v in getattr(spec.fn, "__annotations__", {}).items()
                                if k not in CONTEXT_PARAMS}
        call.__name__ = name
        tools.append(StructuredTool.from_function(coroutine=call, name=name, description=spec.description))
    return tools
