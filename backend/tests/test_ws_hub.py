"""The in-process pub/sub behind the live socket.

The hub is the one place that decides who sees an event, so the tests that
matter are about isolation and about not letting a stalled browser tab
degrade the engine that publishes to it.
"""

import asyncio

import pytest

from backend.ws.hub import Hub


@pytest.fixture
def hub():
    return Hub()


@pytest.mark.asyncio
async def test_a_subscriber_receives_events_on_its_topics(hub):
    connection = hub.connect("alice")
    connection.subscribe(["trades"])

    await hub.publish("alice", "trades", "opened", {"symbol": "RELIANCE"})

    message = await asyncio.wait_for(connection.queue.get(), timeout=1)
    assert message["topic"] == "trades"
    assert message["event"] == "opened"
    assert message["data"] == {"symbol": "RELIANCE"}
    assert message["ts"]


@pytest.mark.asyncio
async def test_events_never_cross_between_users(hub):
    alice = hub.connect("alice")
    alice.subscribe(["trades"])
    bob = hub.connect("bob")
    bob.subscribe(["trades"])

    await hub.publish("bob", "trades", "opened", {"symbol": "TCS"})

    assert alice.queue.empty()
    assert not bob.queue.empty()


@pytest.mark.asyncio
async def test_events_on_untaken_topics_are_not_delivered(hub):
    connection = hub.connect("alice")
    connection.subscribe(["trades"])

    await hub.publish("alice", "pnl", "updated", {})

    assert connection.queue.empty()


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(hub):
    connection = hub.connect("alice")
    connection.subscribe(["trades", "pnl"])
    connection.unsubscribe(["trades"])

    await hub.publish("alice", "trades", "opened", {})
    await hub.publish("alice", "pnl", "updated", {})

    assert (await asyncio.wait_for(connection.queue.get(), timeout=1))["topic"] == "pnl"
    assert connection.queue.empty()


@pytest.mark.asyncio
async def test_two_tabs_for_one_user_both_receive(hub):
    first = hub.connect("alice")
    second = hub.connect("alice")
    first.subscribe(["trades"])
    second.subscribe(["trades"])

    await hub.publish("alice", "trades", "opened", {})

    assert not first.queue.empty()
    assert not second.queue.empty()


@pytest.mark.asyncio
async def test_a_disconnected_connection_stops_receiving(hub):
    connection = hub.connect("alice")
    connection.subscribe(["trades"])
    hub.disconnect(connection)

    await hub.publish("alice", "trades", "opened", {})

    assert connection.queue.empty()
    assert hub.subscribed_symbols() == set()


@pytest.mark.asyncio
async def test_a_stalled_subscriber_drops_its_oldest_events(hub):
    """A browser tab that stops reading must not block the engine loop that
    publishes to it, and must not grow without bound either."""
    connection = hub.connect("alice", max_queue=3)
    connection.subscribe(["trades"])

    for index in range(10):
        await hub.publish("alice", "trades", "opened", {"n": index})

    assert connection.queue.qsize() == 3
    first = await connection.queue.get()
    assert first["data"]["n"] == 7, "the newest events survive, not the stalest"


@pytest.mark.asyncio
async def test_price_topics_report_the_symbols_worth_polling(hub):
    alice = hub.connect("alice")
    alice.subscribe(["prices:RELIANCE", "prices:TCS", "trades"])
    bob = hub.connect("bob")
    bob.subscribe(["prices:RELIANCE"])

    assert hub.subscribed_symbols() == {"RELIANCE", "TCS"}


@pytest.mark.asyncio
async def test_publishing_to_nobody_is_harmless(hub):
    await hub.publish("nobody", "trades", "opened", {})


from backend.ws.hub import Hub, handle_broadcast_event


class _FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, data):
        self.published.append((channel, data))


@pytest.mark.asyncio
async def test_publish_broadcasts_instead_of_delivering_locally_when_redis_is_attached():
    hub = Hub()
    fake_redis = _FakeRedis()
    hub.attach_redis(fake_redis)
    connection = hub.connect("alice")
    connection.subscribe(["trades"])

    await hub.publish("alice", "trades", "opened", {"symbol": "TCS"})

    assert fake_redis.published, "publish() must call broadcast.publish when a redis is attached"
    assert connection.queue.empty(), "no direct local delivery -- that happens via the subscriber loop"


@pytest.mark.asyncio
async def test_deliver_pushes_to_every_matching_connection():
    hub = Hub()
    alice = hub.connect("alice")
    alice.subscribe(["trades"])
    bob = hub.connect("bob")
    bob.subscribe(["trades"])

    message = {"user_id": "alice", "topic": "trades", "event": "opened", "data": {}, "ts": "x"}
    await hub.deliver(message)

    assert not alice.queue.empty()
    assert bob.queue.empty()


@pytest.mark.asyncio
async def test_handle_broadcast_event_delivers_via_the_module_level_hub():
    from backend.ws.hub import hub as real_hub

    connection = real_hub.connect("alice")
    connection.subscribe(["trades"])
    try:
        message = {"user_id": "alice", "topic": "trades", "event": "opened", "data": {}, "ts": "x"}
        await handle_broadcast_event(message)

        assert not connection.queue.empty()
    finally:
        real_hub.disconnect(connection)
