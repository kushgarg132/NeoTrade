"""One read per request: parts of a page that ask the same thing share the answer."""

import asyncio

from backend.core import request_memo


def _reader():
    calls = []

    async def read():
        calls.append(1)
        await asyncio.sleep(0)
        return [{"pnl": 1}]

    return calls, read


async def test_outside_a_request_every_call_reads():
    calls, read = _reader()
    await asyncio.create_task(request_memo.once("k", read))
    await asyncio.create_task(request_memo.once("k", read))
    assert len(calls) == 2


async def test_concurrent_callers_share_one_read_and_cannot_change_each_others_result():
    calls, read = _reader()

    async def page():
        request_memo.start()
        return await asyncio.gather(request_memo.once("k", read), request_memo.once("k", read))

    first, second = await asyncio.create_task(page())
    first[0]["pnl"] = 99
    assert len(calls) == 1 and second == [{"pnl": 1}]


async def test_different_keys_read_separately():
    calls, read = _reader()

    async def page():
        request_memo.start()
        await asyncio.gather(request_memo.once("a", read), request_memo.once("b", read))

    await asyncio.create_task(page())
    assert len(calls) == 2
