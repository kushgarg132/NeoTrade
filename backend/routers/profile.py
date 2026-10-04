"""/profile -- the signed-in user's Google identity plus what they tell
NeoTrade about themselves for the AI. No endpoint takes a user id."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.profile.models import MemoryRefused, ProfileUpdate
from backend.profile.store import ProfileStore

router = APIRouter(prefix="/profile", tags=["Profile"])


def get_profile_store() -> ProfileStore:
    return ProfileStore(db.db)


class MemoryRequest(BaseModel):
    text: str


@router.get("")
async def read_profile(user: User = Depends(get_current_user), store: ProfileStore = Depends(get_profile_store)):
    account = {k: getattr(user, k) for k in ("name", "email", "picture", "role", "created_at")}
    return {"account": account, "profile": await store.get(user.id)}


@router.put("")
async def update_profile(req: ProfileUpdate, user: User = Depends(get_current_user),
                         store: ProfileStore = Depends(get_profile_store)):
    return await store.update(user.id, req.fields())


@router.post("/memories", status_code=201)
async def add_memory(req: MemoryRequest, user: User = Depends(get_current_user),
                     store: ProfileStore = Depends(get_profile_store)):
    try:
        return await store.add_memory(user.id, req.text, "manual")
    except MemoryRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, user: User = Depends(get_current_user),
                        store: ProfileStore = Depends(get_profile_store)):
    if not await store.delete_memory(user.id, memory_id):
        raise HTTPException(status_code=404, detail="No such memory.")
    return Response(status_code=204)
