"""The daily answer for the user's own account (Phase 19.E): where the
portfolio stands, what moved and why, AI against the user, and the two
Telegram messages built from it -- 08:45 IST before the open, and after the
16:00 pass's review.

Pricing never calls a broker: the last snapshot's holdings are repriced from
market quotes (service.quoted), so Today can poll it every minute."""

import logging
from datetime import datetime, time, timedelta, timezone
from html import escape
from typing import Optional

from backend.engine.session import IST

logger = logging.getLogger(__name__)

MOVERS = 3
NEWS_LOOKBACK = timedelta(hours=36)
PREMARKET, PREMARKET_END = time(8, 45), time(9, 15)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


def _move_pct(row: dict) -> Optional[float]:
    last, close = row.get("last_price"), row.get("close_price")
    return (last / close - 1) * 100 if last and close else None


async def verdicts_visible(db, user_id: str) -> bool:
    from backend.app_settings import AppSettingsStore

    user = await db["users"].find_one({"id": user_id}, {"role": 1}) or {}
    return user.get("role") == "admin" or await AppSettingsStore(db).get_portfolio_verdicts() == "all"


async def headlines_for(db, symbols: list[str], since: datetime) -> dict[str, dict]:
    """symbol -> the most material scored headline about it since `since`."""
    if not symbols:
        return {}
    best: dict[str, tuple[float, dict]] = {}
    cursor = db["news_items"].find(
        {"published_at": {"$gte": since}, "impacts.target": {"$in": symbols}},
        {"title": 1, "event": 1, "url": 1, "published_at": 1, "impacts": 1},
    ).sort("published_at", -1).limit(300)
    async for item in cursor:
        for impact in item.get("impacts") or []:
            target = impact.get("target")
            if target in symbols and (impact.get("impact") or 0) > best.get(target, (-1, None))[0]:
                best[target] = (impact.get("impact") or 0, {
                    "title": item.get("event") or item.get("title"), "url": item.get("url"),
                    "direction": impact.get("direction"), "published_at": _aware(item.get("published_at")),
                })
    return {symbol: found for symbol, (_, found) in best.items()}


async def pulse(db, user_id: str, now: Optional[datetime] = None) -> Optional[dict]:
    """The user's own account right now: value, gain, today's move, the
    biggest movers with the headline behind each, and verdict changes from
    the last review. None before the first portfolio read."""
    from backend.brokers.roles import brokers_for
    from backend.portfolio.service import latest_snapshot, quoted, scorecard_for
    from backend.prefs import PrefsStore

    now = now or datetime.now(timezone.utc)
    snapshot = await latest_snapshot(db, user_id)
    if not snapshot:
        return None
    raw, priced = await quoted(db, snapshot.get("raw_holdings") or [], now)
    mine = brokers_for((await PrefsStore(db).get(user_id)).get("broker_roles") or {}, "mine")
    card = scorecard_for({**snapshot, "raw_holdings": raw}, mine or {h.get("broker") for h in raw}, [], [])
    totals = card["totals"]
    base = (totals["value"] or 0) - (totals["day_change"] or 0)
    rows = [r for r in card["holdings"] if r.get("kind", "STOCK") == "STOCK" and _move_pct(r) is not None]
    rows.sort(key=lambda r: abs(_move_pct(r)), reverse=True)
    top = rows[:MOVERS]
    why = await headlines_for(db, [r["symbol"] for r in top], now - NEWS_LOOKBACK)
    changes = []
    if await verdicts_visible(db, user_id):
        changes = [{"symbol": r["symbol"], "from": r["previous_verdict"], "to": r["verdict"],
                    "reasons": r.get("reason_codes") or []}
                   for r in card["holdings"] if r.get("previous_verdict") and r.get("verdict")
                   and r["verdict"] != r["previous_verdict"]]
    return {
        "as_of": now if priced else _aware(snapshot["at"]), "holdings_as_of": _aware(snapshot["at"]),
        "value": round(totals["value"] or 0, 2), "invested": round(totals["invested"] or 0, 2),
        "pnl": round(totals["pnl"] or 0, 2), "pnl_pct": totals["pnl_pct"],
        "day_change": round(totals["day_change"] or 0, 2),
        "day_change_pct": (totals["day_change"] or 0) / base * 100 if base else None,
        "count": totals["count"],
        "movers": [{"symbol": r["symbol"], "move_pct": round(_move_pct(r), 2), "day_change": round(r["day_change"] or 0, 2),
                    "why": why.get(r["symbol"])} for r in top],
        "verdict_changes": changes,
    }


async def pnl_since(db, user_id: str, roles: dict, since: datetime) -> dict:
    """Closed P&L since `since`, net of charges on both sides: the user's own
    account from the journal (charges estimated as the journal mirror does,
    since a broker's trade book carries none) and the whole AI book."""
    from backend.autopilot.service import ai_book_query
    from backend.brokers.roles import brokers_for
    from backend.journal import mirror
    from backend.journal.roundtrips import build_round_trips
    from backend.journal.store import JournalStore

    mine_brokers = brokers_for(roles, "mine")
    # Round trips over the whole history (a position bought before `since`
    # and sold after it counts), kept if they closed since.
    trades = [t for t in await JournalStore(db).list_trades(user_id)
              if not mine_brokers or t.get("broker") in mine_brokers]
    closed = [t for t in build_round_trips(trades)
              if t.get("pnl") is not None and (_aware(t.get("closed_at")) or since) >= since]
    ids = {i for trip in closed for i in trip["trade_ids"]}
    mine_charges = mirror.costs([t for t in trades if t["_id"] in ids], closed, 0)["charges"]
    mine = sum(t["pnl"] for t in closed) - mine_charges
    ai = ai_charges = 0.0
    async for t in db["paper_trades"].find(ai_book_query(user_id)):
        if t.get("status") == "CLOSED" and (_aware(t.get("exit_at")) or since) >= since:
            ai += t.get("realized_pnl") or 0.0
            ai_charges += t.get("costs") or 0.0
    return {"mine": round(mine, 2), "mine_charges": round(mine_charges, 2),
            "ai": round(ai - ai_charges, 2), "ai_charges": round(ai_charges, 2)}


def day_start(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(IST).date(), time(0, 0), tzinfo=IST)


def month_start(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(IST).date().replace(day=1), time(0, 0), tzinfo=IST)


async def scoreboard(db, user_id: str, roles: dict, now: datetime) -> dict:
    """AI against the user, closed and net of charges: today and this month."""
    return {"today": await pnl_since(db, user_id, roles, day_start(now)),
            "month": await pnl_since(db, user_id, roles, month_start(now))}


# ------------------------------------------------------------------ Telegram


def _rupees(value: Optional[float], sign: bool = False) -> str:
    if value is None:
        return "—"
    return f"{'+' if sign and value > 0 else '−' if value < 0 else ''}₹{abs(value):,.0f}"


def _pct(value: Optional[float]) -> str:
    return "" if value is None else f" ({value:+.1f}%)"


def premarket_text(p: Optional[dict], overnight: dict[str, dict], ideas: int, ai: dict) -> str:
    lines = ["☀️ <b>Before the open</b>"]
    if p:
        lines.append(f"Your account: {_rupees(p['value'])}, yesterday {_rupees(p['day_change'], True)}{_pct(p['day_change_pct'])}")
    if overnight:
        lines.append("News on your holdings since the close:")
        lines += [f"• {escape(sym)}: {escape(n['title'] or '')}" for sym, n in list(overnight.items())[:5]]
    else:
        lines.append("No material news on your holdings since the close.")
    lines.append(f"Ideas for your account: {ideas}" if ideas else
                 "No ideas for your account: no strategy has earned it yet.")
    mode = "off" if not ai.get("enabled") else ("live" if ai.get("live") else "paper")
    lines.append(f"AI account: autopilot {mode}, {_rupees(ai.get('deployed'))} deployed.")
    return "\n".join(lines)


def postclose_text(p: Optional[dict], today: dict, events: list[dict]) -> str:
    lines = ["🔔 <b>After the close</b>"]
    if p:
        lines.append(f"Your account: {_rupees(p['value'])}, today {_rupees(p['day_change'], True)}{_pct(p['day_change_pct'])}, "
                     f"overall {_rupees(p['pnl'], True)}{_pct(p['pnl_pct'])}")
        if p["movers"]:
            lines.append("Moved most:")
            for m in p["movers"]:
                why = f" — {escape(m['why']['title'])}" if m.get("why") and m["why"].get("title") else ""
                lines.append(f"• {escape(m['symbol'])} {m['move_pct']:+.1f}%{why}")
        for c in p["verdict_changes"]:
            lines.append(f"⚠️ {escape(c['symbol'])}: {c['from']} → {c['to']}")
    lines.append(f"Closed today, net: you {_rupees(today['mine'], True)} · AI {_rupees(today['ai'], True)}")
    if events:
        lines.append("Tomorrow: " + "; ".join(escape(e.get("event") or e.get("title") or "") for e in events[:3]))
    return "\n".join(lines)


async def _ai_line(db, user_id: str, prefs: dict) -> dict:
    from backend.autopilot.service import open_trades

    deployed = sum((t.get("quantity") or 0) * (t.get("entry_price") or 0) for t in await open_trades(db, user_id))
    return {"enabled": prefs.get("autopilot_enabled"), "live": prefs.get("autopilot_live"), "deployed": deployed}


async def _users(db) -> list[str]:
    return sorted(set(await db["portfolio_snapshots"].distinct("user_id")) | set(
        await db["user_prefs"].distinct("user_id", {"broker_roles": {"$exists": True, "$ne": {}}})))


async def send_premarket(db, redis, now: datetime) -> int:
    """Weekdays 08:45-09:15 IST, once a day per user."""
    from backend.portfolio.service import mine_holdings
    from backend.prefs import PrefsStore
    from backend.risk.paper_gate import for_mine
    from backend.suggestions.notify import notify

    local = now.astimezone(IST)
    if local.weekday() >= 5 or not (PREMARKET <= local.time() < PREMARKET_END):
        return 0
    sent = 0
    for user_id in await _users(db):
        if not await redis.set(f"digest:pre:{user_id}:{local.date()}", "1", nx=True, px=86_400_000):
            continue
        try:
            prefs = await PrefsStore(db).get(user_id)
            p = await pulse(db, user_id, now)
            held = list(await mine_holdings(db, user_id))
            last_close = datetime.combine(local.date() - timedelta(days=1), time(15, 30), tzinfo=IST)
            overnight = await headlines_for(db, held, last_close)
            ideas = len(await for_mine(db, user_id, await db["suggestions"].find(
                {"user_id": user_id, "status": "PENDING", "mode": "LONGTERM"}).to_list(length=200)))
            await notify(db, user_id, premarket_text(p, overnight, ideas, await _ai_line(db, user_id, prefs)))
            sent += 1
        except Exception as exc:
            logger.exception("pre-market digest failed for %s: %s", user_id, exc)
    return sent


async def send_postclose(db, now: datetime) -> int:
    """After the 16:00 pass's review (backend/scheduler.py). Skipped when the
    pass runs as the next morning's catch-up: an evening message at 9 AM is noise."""
    from backend.datalayer import market
    from backend.prefs import PrefsStore
    from backend.suggestions.notify import notify

    if now.astimezone(IST).time() < time(15, 30):
        return 0
    events = await market.upcoming(db, hours=24, now=now)
    sent = 0
    for user_id in await _users(db):
        try:
            roles = (await PrefsStore(db).get(user_id)).get("broker_roles") or {}
            text = postclose_text(await pulse(db, user_id, now), await pnl_since(db, user_id, roles, day_start(now)), events)
            await notify(db, user_id, text)
            sent += 1
        except Exception as exc:
            logger.exception("post-close digest failed for %s: %s", user_id, exc)
    return sent
