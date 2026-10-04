"""Guardrail breaches already alerted (collection `guardrail_events`, one per
user + IST day + breach key -- the dedupe that makes a 60-second poll send
one alert, not hundreds) and where to send alerts (collection
`alert_channels`, one per user; not part of prefs, since a user must not be
able to point alerts at a chat they did not link themselves). A user's own
Telegram bot token lives there too, Fernet-encrypted with the same key as
broker credentials, and is never returned to the client."""

from datetime import date, datetime, timezone
from typing import Optional

from backend.auth.broker_credentials import fernet_from_settings


class GuardrailStore:
    def __init__(self, db) -> None:
        self.events = db["guardrail_events"]
        self.channels = db["alert_channels"]

    async def ensure_indexes(self) -> None:
        await self.events.create_index([("user_id", 1), ("day", 1)])

    async def record(self, user_id: str, day: date, breach: dict) -> bool:
        """True only the first time this breach is seen that day."""
        result = await self.events.update_one(
            {"_id": f"{user_id}:{day.isoformat()}:{breach['key']}"},
            {"$setOnInsert": {**breach, "user_id": user_id, "day": day.isoformat(),
                              "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return result.upserted_id is not None

    async def events_for(self, user_id: str, day: date) -> list[dict]:
        docs = await self.events.find({"user_id": user_id, "day": day.isoformat()}).to_list(length=None)
        docs.sort(key=lambda d: d["at"])
        return [{k: v for k, v in d.items() if k not in ("_id", "user_id")} for d in docs]

    async def telegram_chat(self, user_id: str) -> Optional[int]:
        doc = await self.channels.find_one({"_id": user_id})
        return doc.get("telegram_chat_id") if doc else None

    async def set_telegram_chat(self, user_id: str, chat_id: Optional[int]) -> None:
        await self.channels.update_one(
            {"_id": user_id}, {"$set": {"telegram_chat_id": chat_id}}, upsert=True,
        )

    async def telegram_bot(self, user_id: str) -> Optional[dict]:
        """{"token", "username"} of the user's own bot, decrypted; None when
        they use the server's bot (or the key to decrypt it is gone)."""
        doc = await self.channels.find_one({"_id": user_id}) or {}
        fernet = fernet_from_settings()
        if not doc.get("telegram_bot_token") or fernet is None:
            return None
        return {"token": fernet.decrypt(doc["telegram_bot_token"].encode()).decode(),
                "username": doc.get("telegram_bot_username")}

    async def set_telegram_bot(self, user_id: str, token: Optional[str], username: Optional[str] = None) -> None:
        """A different bot cannot message a chat linked to the old one, so
        changing the bot always unlinks the chat."""
        fernet = fernet_from_settings()
        if token is not None and fernet is None:
            raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is not set; refusing to store a bot token in plain text")
        await self.channels.update_one({"_id": user_id}, {"$set": {
            "telegram_bot_token": fernet.encrypt(token.encode()).decode() if token else None,
            "telegram_bot_username": username if token else None,
            "telegram_chat_id": None,
        }}, upsert=True)

    async def telegram_channel(self, user_id: str) -> Optional[tuple[Optional[str], int]]:
        """(bot token or None for the server bot, chat id) to alert this user
        through; None when nothing can reach them."""
        from backend.guardrails import telegram

        chat_id = await self.telegram_chat(user_id)
        if chat_id is None:
            return None
        bot = await self.telegram_bot(user_id)
        if bot is None and not telegram.configured():
            return None
        return (bot["token"] if bot else None, chat_id)
