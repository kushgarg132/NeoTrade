"""One read per request, for pages whose parts each ask the same thing.

A handler calls `start()`; until the request ends, `once(key, read)` runs `read`
one time per key and hands every caller its own copy. Tasks the handler spawns
inherit the scope. Outside a scope `once` just reads, so nothing else changes.
Read-only pages only: a write in the request would not be seen by a later `once`.
"""

import asyncio
import copy
from contextvars import ContextVar
from typing import Awaitable, Callable, Hashable, Optional

_reads: ContextVar[Optional[dict]] = ContextVar("request_reads", default=None)


def start() -> None:
    _reads.set({})


async def once(key: Hashable, read: Callable[[], Awaitable]):
    reads = _reads.get()
    if reads is None:
        return await read()
    if key not in reads:
        reads[key] = asyncio.ensure_future(read())
    return copy.deepcopy(await asyncio.shield(reads[key]))
