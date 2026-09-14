"""backend/broadcast.py: the cross-worker event bus. publish() and listen()
are the only two primitives -- everything else (ws/hub.py's fan-out,
routers/trading.py's cross-worker cancel) is built on top of these.
"""

import json

import pytest

from backend import broadcast


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages
        self.subscribed = []
        self.closed = False

    async def subscribe(self, *channels):
        self.subscribed.extend(channels)

    async def listen(self):
        for message in self._messages:
            yield message

    async def close(self):
        self.closed = True


class _FakeRedis:
    def __init__(self, messages=None):
        self._messages = messages or []
        self.published = []

    def pubsub(self):
        return _FakePubSub(self._messages)

    async def publish(self, channel, data):
        self.published.append((channel, data))


async def test_publish_is_a_noop_when_redis_is_none():
    await broadcast.publish(None, "ws:events", {"a": 1})  # must not raise


async def test_publish_sends_the_payload_as_json():
    redis = _FakeRedis()

    await broadcast.publish(redis, "ws:events", {"symbol": "RELIANCE"})

    assert redis.published == [("ws:events", json.dumps({"symbol": "RELIANCE"}))]


async def test_listen_is_a_noop_when_redis_is_none():
    await broadcast.listen(None, {"ws:events": lambda payload: None})  # must return, not hang


async def test_listen_dispatches_to_the_handler_registered_for_the_channel():
    received = []

    async def handler(payload):
        received.append(payload)

    messages = [
        {"type": "subscribe", "channel": "ws:events", "data": 1},  # subscribe ack, must be ignored
        {"type": "message", "channel": "ws:events", "data": json.dumps({"symbol": "TCS"})},
    ]
    redis = _FakeRedis(messages)

    await broadcast.listen(redis, {"ws:events": handler})

    assert received == [{"symbol": "TCS"}]


async def test_listen_ignores_messages_on_unregistered_channels():
    received = []

    async def handler(payload):
        received.append(payload)

    messages = [{"type": "message", "channel": "some:other:channel", "data": json.dumps({})}]
    redis = _FakeRedis(messages)

    await broadcast.listen(redis, {"ws:events": handler})

    assert received == []


async def test_one_handler_failing_does_not_stop_dispatch_to_the_next_message():
    received = []

    async def flaky_handler(payload):
        if payload.get("boom"):
            raise RuntimeError("handler exploded")
        received.append(payload)

    messages = [
        {"type": "message", "channel": "ws:events", "data": json.dumps({"boom": True})},
        {"type": "message", "channel": "ws:events", "data": json.dumps({"ok": True})},
    ]
    redis = _FakeRedis(messages)

    await broadcast.listen(redis, {"ws:events": flaky_handler})

    assert received == [{"ok": True}]


async def test_listen_subscribes_to_every_handler_channel():
    redis = _FakeRedis([])
    pubsub_holder = {}

    original_pubsub = redis.pubsub

    def capturing_pubsub():
        ps = original_pubsub()
        pubsub_holder["ps"] = ps
        return ps

    redis.pubsub = capturing_pubsub

    await broadcast.listen(redis, {"ws:events": lambda p: None, "runs:cancel": lambda p: None})

    assert set(pubsub_holder["ps"].subscribed) == {"ws:events", "runs:cancel"}
