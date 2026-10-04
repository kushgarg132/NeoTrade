"""What a user tells NeoTrade about themselves, for the AI to use. Every
field is optional; an empty string or list clears it."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_MEMORIES = 50
MAX_MEMORY_CHARS = 200
MAX_LIST_ITEMS, MAX_ITEM_CHARS = 20, 40

Style = Literal["intraday", "swing", "longterm", "options"]


class MemoryRefused(ValueError):
    """A memory that cannot be saved; the message is shown to the user."""


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=60)
    experience: Optional[Literal["beginner", "intermediate", "advanced", ""]] = None
    risk_appetite: Optional[Literal["low", "medium", "high", ""]] = None
    styles: Optional[list[Style]] = None
    horizon: Optional[str] = Field(None, max_length=60)
    goals: Optional[str] = Field(None, max_length=500)
    favour: Optional[list[str]] = None
    avoid: Optional[list[str]] = None
    constraints: Optional[str] = Field(None, max_length=500)
    about_me: Optional[str] = Field(None, max_length=1500)
    answer_style: Optional[str] = Field(None, max_length=1500)

    @field_validator("display_name", "horizon", "goals", "constraints", "about_me", "answer_style", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("styles", "favour", "avoid", mode="before")
    @classmethod
    def _blank_list(cls, value):
        # A blank string from a form means "clear this list", same as [].
        return [] if isinstance(value, str) and not value.strip() else value

    @field_validator("styles")
    @classmethod
    def _unique(cls, value):
        return list(dict.fromkeys(value)) if value is not None else value

    @field_validator("favour", "avoid")
    @classmethod
    def _items(cls, value):
        if value is None:
            return value
        items = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        if len(items) > MAX_LIST_ITEMS:
            raise ValueError(f"at most {MAX_LIST_ITEMS} items")
        if any(len(v) > MAX_ITEM_CHARS for v in items):
            raise ValueError(f"each item at most {MAX_ITEM_CHARS} characters")
        return items

    def fields(self) -> dict:
        return self.model_dump(exclude_unset=True)
