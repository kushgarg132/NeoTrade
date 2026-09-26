"""Phase 12's two numbers: are beta users coming back every week, and do they
open the journal after a losing day (the moment the product exists for).

Activity is one document per user per IST day they opened the journal
(collection `journal_opens`) -- recorded by GET /journal, nothing else.
"""

from datetime import date, datetime, timedelta, timezone

from backend.engine.session import IST
from backend.journal.roundtrips import build_round_trips, daily_pnl
from backend.journal.store import JournalStore


async def record_open(db, user_id: str, now: datetime | None = None) -> None:
    day = (now or datetime.now(timezone.utc)).astimezone(IST).date().isoformat()
    await db["journal_opens"].update_one(
        {"_id": f"{user_id}:{day}"}, {"$setOnInsert": {"user_id": user_id, "day": day}}, upsert=True,
    )


def _opened_after_loss(open_days: list[str], calendar: list[dict]) -> tuple[int, int]:
    """(losing days followed by an open, losing days that had a later open
    window at all). A losing day counts as "followed" if the journal was
    opened that same evening or on the next day with any activity."""
    losing = [row["day"] for row in calendar if row["pnl"] < 0]
    opens = sorted(open_days)
    followed = 0
    for day in losing:
        limit = (date.fromisoformat(day) + timedelta(days=3)).isoformat()  # covers a weekend
        if any(day <= o <= limit for o in opens):
            followed += 1
    return followed, len(losing)


async def beta_metrics(db, now: datetime | None = None) -> dict:
    today = (now or datetime.now(timezone.utc)).astimezone(IST).date()
    week_ago = (today - timedelta(days=6)).isoformat()
    two_weeks_ago = (today - timedelta(days=13)).isoformat()

    users = await db["users"].find({}).to_list(length=None)
    opens = await db["journal_opens"].find({}).to_list(length=None)
    by_user: dict[str, list[str]] = {}
    for o in opens:
        by_user.setdefault(o["user_id"], []).append(o["day"])

    active_week = {u for u, days in by_user.items() if any(d >= week_ago for d in days)}
    active_last_week = {u for u, days in by_user.items() if any(two_weeks_ago <= d < week_ago for d in days)}

    store = JournalStore(db)
    with_trades = followed = losing = 0
    for user in users:
        trades = await store.list_trades(user["id"])
        if not trades:
            continue
        with_trades += 1
        f, l = _opened_after_loss(by_user.get(user["id"], []), daily_pnl(build_round_trips(trades)))
        followed += f
        losing += l

    prefs = db["user_prefs"]
    return {
        "users": len(users),
        "users_with_trades": with_trades,
        "weekly_active": len(active_week),
        "returned_from_last_week": len(active_week & active_last_week),
        "active_last_week": len(active_last_week),
        "guardrails_on": await prefs.count_documents({"guardrails_enabled": True}),
        "telegram_linked": await db["alert_channels"].count_documents({"telegram_chat_id": {"$ne": None}}),
        "losing_days": losing,
        "losing_days_followed_by_open": followed,
    }
