"""The profile store: partial updates, validated fields, memories with a cap,
and no way for one user to see or change another's profile."""

import pytest
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from backend.profile.models import MAX_MEMORIES, MemoryRefused, ProfileUpdate
from backend.profile.store import ProfileStore


@pytest.fixture
def store():
    return ProfileStore(AsyncMongoMockClient()["test_db"])


async def test_update_is_partial_and_blank_clears(store):
    await store.update("alice", {"goals": "retire early", "experience": "advanced"})
    await store.update("alice", {"goals": ""})
    profile = await store.get("alice")
    assert profile["experience"] == "advanced"
    assert "goals" not in profile


def test_profile_update_rejects_over_limits():
    for bad in ({"goals": "x" * 501}, {"favour": ["x" * 41]}, {"favour": [f"s{i}" for i in range(21)]}, {"experience": "pro"},
                {"styles": ["scalping"]}, {"display_name": "x" * 61}, {"about_me": "x" * 1501}):
        with pytest.raises(ValidationError):
            ProfileUpdate(**bad)


def test_profile_update_strips_dedupes_and_keeps_only_set_fields():
    update = ProfileUpdate(display_name="  Kush ", styles=["swing", "swing", "longterm"], favour=[" IT ", ""])
    assert update.fields() == {"display_name": "Kush", "styles": ["swing", "longterm"], "favour": ["IT"]}
    assert ProfileUpdate(goals="   ").fields() == {"goals": ""}


async def test_memory_add_dedupe_cap_delete(store):
    memory = await store.add_memory("alice", "Saving for a house", "chat")
    assert memory["source"] == "chat" and memory["text"] == "Saving for a house"
    with pytest.raises(MemoryRefused):
        await store.add_memory("alice", "  saving for a  HOUSE ", "manual")
    with pytest.raises(MemoryRefused):
        await store.add_memory("alice", "   ", "manual")
    with pytest.raises(MemoryRefused):
        await store.add_memory("alice", "x" * 201, "manual")
    for i in range(MAX_MEMORIES - 1):
        await store.add_memory("alice", f"fact {i}", "manual")
    with pytest.raises(MemoryRefused):
        await store.add_memory("alice", "one too many", "manual")
    assert await store.delete_memory("alice", memory["id"]) is True
    assert await store.delete_memory("alice", memory["id"]) is False


async def test_users_are_isolated(store):
    await store.update("alice", {"risk_appetite": "high"})
    memory = await store.add_memory("alice", "Saving for a house", "chat")
    assert await store.get("bob") == {"memories": []}
    assert await store.delete_memory("bob", memory["id"]) is False
    assert len((await store.get("alice"))["memories"]) == 1


def test_blank_string_clears_a_list_field():
    # The page sends "" for a list field the user never set; that means "clear", not a 422.
    assert ProfileUpdate(styles="", favour="", avoid=None).fields() == {"styles": [], "favour": [], "avoid": None}
