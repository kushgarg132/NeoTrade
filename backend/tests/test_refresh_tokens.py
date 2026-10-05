"""RefreshTokenStore: the long-lived credential behind silent re-login.

Only a hash of the raw token ever touches Mongo -- a database read can never
hand back something usable as a credential. Every refresh rotates: the old
token dies the moment a new one is issued, and presenting an already-dead
token again (replay of a stolen or superseded token) revokes the user's
whole chain rather than quietly failing, since that pattern is the signature
of theft, not a client bug.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.auth.refresh_store import RefreshTokenStore


@pytest.fixture
def store():
    client = AsyncMongoMockClient()
    return RefreshTokenStore(client["test_db"])


@pytest.mark.asyncio
async def test_issue_returns_a_usable_raw_token(store):
    raw = await store.issue("user-1")
    assert isinstance(raw, str)
    assert len(raw) >= 32


@pytest.mark.asyncio
async def test_the_raw_token_is_never_stored_in_the_clear(store):
    raw = await store.issue("user-1")
    doc = await store.collection.find_one({"user_id": "user-1"})
    assert doc is not None
    assert raw not in doc.values()
    assert "token_hash" in doc


@pytest.mark.asyncio
async def test_rotate_returns_the_owning_user_and_a_new_token(store):
    raw = await store.issue("user-1")

    result = await store.rotate(raw)

    assert result is not None
    user_id, new_raw = result
    assert user_id == "user-1"
    assert new_raw != raw


@pytest.mark.asyncio
async def test_the_old_token_stops_working_once_rotated(store):
    raw = await store.issue("user-1")
    await store.rotate(raw)

    assert await store.rotate(raw, now=datetime.now(timezone.utc) + timedelta(minutes=1)) is None


@pytest.mark.asyncio
async def test_the_new_token_from_rotation_works(store):
    raw = await store.issue("user-1")
    _, new_raw = await store.rotate(raw)

    result = await store.rotate(new_raw)

    assert result is not None
    assert result[0] == "user-1"


@pytest.mark.asyncio
async def test_an_unknown_token_returns_none(store):
    assert await store.rotate("not-a-real-token") is None


@pytest.mark.asyncio
async def test_an_expired_token_is_refused(store):
    raw = await store.issue("user-1", now=datetime.now(timezone.utc) - timedelta(days=100))

    assert await store.rotate(raw) is None


@pytest.mark.asyncio
async def test_reusing_a_rotated_away_token_revokes_the_whole_chain(store):
    """Presenting a token that was already rotated away is what a stolen or
    duplicated token replay looks like -- the honest client already moved on
    to the newer one. The right response is to kill every live token for
    that user, not just refuse the one request."""
    raw = await store.issue("user-1")
    _, second = await store.rotate(raw)
    _, third = await store.rotate(second)

    # The attacker replays the first (dead) token, well after the rotation.
    result = await store.rotate(raw, now=datetime.now(timezone.utc) + timedelta(minutes=1))

    assert result is None
    # The legitimate, still-current token is dead too now.
    assert await store.rotate(third) is None


@pytest.mark.asyncio
async def test_revoke_kills_one_token_without_touching_others(store):
    a = await store.issue("user-1")
    b = await store.issue("user-1")

    await store.revoke(a)

    assert await store.rotate(a) is None
    result = await store.rotate(b)
    assert result is not None


@pytest.mark.asyncio
async def test_revoke_all_kills_every_token_for_that_user_only(store):
    mine_a = await store.issue("user-1")
    mine_b = await store.issue("user-1")
    theirs = await store.issue("user-2")

    await store.revoke_all("user-1")

    assert await store.rotate(mine_a) is None
    assert await store.rotate(mine_b) is None
    assert await store.rotate(theirs) is not None


@pytest.mark.asyncio
async def test_revoking_an_unknown_token_does_not_raise(store):
    await store.revoke("not-a-real-token")


@pytest.mark.asyncio
async def test_two_tabs_refreshing_at_once_both_stay_signed_in(store):
    """Tabs share the refresh cookie and can refresh in the same instant. The
    slower one presented a token the faster one had just rotated, which read
    as a replay and logged every session out."""
    import asyncio

    raw = await store.issue("user-1")
    first, second = await asyncio.gather(store.rotate(raw), store.rotate(raw))

    assert first is not None and second is not None
    assert first[1] != second[1]
    assert await store.rotate(first[1]) is not None
    assert await store.rotate(second[1]) is not None


@pytest.mark.asyncio
async def test_a_token_is_rotated_away_only_once(store):
    raw = await store.issue("user-1")
    await store.rotate(raw)
    rotated = await store.collection.count_documents({"rotated": True})
    assert rotated == 1
