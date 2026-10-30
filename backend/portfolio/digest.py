"""The daily answer for the user's own account (Phase 19.E): where the
portfolio stands, what moved and why, AI against the user, and the two
Telegram messages built from it -- 08:45 IST before the open, and after the
16:00 pass's review.

Pricing never calls a broker: the last snapshot's holdings are repriced from
market quotes (service.quoted), so Today can poll it every minute."""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from html import escape
from typing import Optional

from backend.core.market_calendar import is_trading_day, last_trading_day
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
    from backend.auth.broker_credentials import get_credential_store
    from backend.brokers.roles import brokers_for
    from backend.database import db as handle
    from backend.portfolio.service import fetch_holdings, latest_snapshot, quoted, scorecard_for
    from backend.prefs import PrefsStore

    now = now or datetime.now(timezone.utc)
    snapshot = await latest_snapshot(db, user_id)
    if not snapshot:
        return None
    # A logged-in broker is read now (its own prices and previous close, as
    # Mine -> Holdings shows); only a logged-out one is carried and quoted.
    try:
        live, _, carried = await fetch_holdings(user_id, get_credential_store(), handle.redis, snapshot, db)
    except Exception as exc:
        logger.warning("pulse: broker read failed for %s, quoting the snapshot: %s", user_id, exc)
        live, carried = [], None
    if carried is None:
        rest = snapshot.get("raw_holdings") or []
    else:
        rest = [h.model_dump() for h in carried]
    rest, priced = await quoted(db, rest, now, _aware(snapshot["at"])) if rest else (rest, False)
    raw = [h.model_dump() for h in live] + rest
    priced = priced or bool(live)
    mine = brokers_for((await PrefsStore(db).get(user_id)).get("broker_roles") or {}, "mine")
    card = scorecard_for({**snapshot, "raw_holdings": raw}, mine or {h.get("broker") for h in raw}, [], [])
    totals = card["totals"]
    # Today's % over holdings whose day move is known: the others' value would dilute it.
    known = [r for r in card["holdings"] if r.get("close_price") and r.get("value") is not None]
    base = sum(r["value"] for r in known) - (totals["day_change"] or 0)
    rows = [r for r in card["holdings"] if r.get("kind", "STOCK") == "STOCK" and _move_pct(r) is not None]
    rows.sort(key=lambda r: abs(_move_pct(r)), reverse=True)
    top = rows[:MOVERS]
    why = await headlines_for(db, [r["symbol"] for r in top], now - NEWS_LOOKBACK)
    try:  # display only: a failure leaves the list empty, never the pulse
        from backend.portfolio import news_moves
        moved = await news_moves.today(db, [{"symbol": r["symbol"], "move_pct": _move_pct(r),
                                             "rupees": r.get("day_change") or 0} for r in rows], now)
    except Exception as exc:
        logger.warning("pulse: news moves failed for %s: %s", user_id, exc)
        moved = []
    changes = []
    # Only from the latest trading day's review: a failing review must not
    # replay the same "HOLD -> SELL" in Do today and every evening message.
    from backend.core.market_calendar import previous_trading_day
    reviewed = _aware(snapshot["at"]).astimezone(IST).date() >= previous_trading_day(now.astimezone(IST).date())
    if reviewed and await verdicts_visible(db, user_id):
        changes = [{"symbol": r["symbol"], "from": r["previous_verdict"], "to": r["verdict"],
                    "reasons": r.get("reason_codes") or []}
                   for r in card["holdings"] if r.get("previous_verdict") and r.get("verdict")
                   and r["verdict"] != r["previous_verdict"]]
    return {
        "as_of": now if priced else _aware(snapshot["at"]),
        "holdings_as_of": _aware(snapshot["at"]) if rest else now,
        "value": round(totals["value"] or 0, 2), "invested": round(totals["invested"] or 0, 2),
        "pnl": round(totals["pnl"] or 0, 2), "pnl_pct": totals["pnl_pct"],
        "day_change": round(totals["day_change"] or 0, 2),
        "day_change_pct": (totals["day_change"] or 0) / base * 100 if base else None,
        "count": totals["count"],
        "pnl_by_symbol": {r["symbol"]: round(r["pnl"], 2) for r in card["holdings"] if r.get("pnl") is not None},
        "movers": [{"symbol": r["symbol"], "move_pct": round(_move_pct(r), 2), "day_change": round(r["day_change"] or 0, 2),
                    "why": why.get(r["symbol"])} for r in top],
        "verdict_changes": changes,
        "news_moves": moved,
    }


PULSE_TTL_S = 30
_PULSE_CACHE: dict = {}  # (id(db), user_id) -> (monotonic at, task)


async def cached_pulse(db, user_id: str, now: Optional[datetime] = None) -> Optional[dict]:
    """`pulse` for a page request, shared for PULSE_TTL_S per user and process: it reads the
    broker and quotes, the slowest part of Home/Money/AI (0.1-0.5 s), and those pages ask together."""
    from time import monotonic  # this module's `time` is datetime.time

    key = (id(db), user_id)
    hit = _PULSE_CACHE.get(key)
    if hit and monotonic() - hit[0] < PULSE_TTL_S and not (hit[1].done() and hit[1].exception()):
        return await asyncio.shield(hit[1])
    task = asyncio.ensure_future(pulse(db, user_id, now))
    _PULSE_CACHE[key] = (monotonic(), task)
    return await asyncio.shield(task)


async def last_session_move(db, held: dict[str, float], today) -> Optional[dict]:
    """The last session's move of `held` (symbol -> quantity) from the stored
    daily closes. Before the open a quote is still yesterday's close, so a
    pulse there reads about 0 for 'yesterday'."""
    from backend.datalayer import bars
    from backend.core.market_calendar import previous_trading_day

    last = await bars.prev_closes(db, held, today)                       # the last session's close
    before = await bars.prev_closes(db, held, previous_trading_day(today))  # the one before it
    both = [s for s in held if s in last and s in before]
    base = sum(held[s] * before[s] for s in both)
    if not base:
        return None
    change = sum(held[s] * (last[s] - before[s]) for s in both)
    return {"change": round(change, 2), "pct": change / base * 100}


async def pnl_since(db, user_id: str, roles: dict, since: datetime, picks_only: bool = False) -> dict:
    """Closed P&L since `since`, net of charges on both sides: the user's own
    account from the journal (charges estimated as the journal mirror does,
    since a broker's trade book carries none) and the whole AI book -- or,
    with `picks_only`, only its trades credited to a pick (autopilot/picks.py)."""
    from backend.autopilot.service import ai_book_query
    from backend.brokers.roles import brokers_for
    from backend.journal import mirror
    from backend.journal.roundtrips import build_round_trips, instrument_kind
    from backend.journal.store import JournalStore

    mine_brokers = brokers_for(roles, "mine")
    # Round trips over the whole history (a position bought before `since`
    # and sold after it counts), kept if they closed since. Stocks only, as
    # Mine everywhere (`lots.py::mine_trades`): the AI book is equity.
    trades = [t for t in await JournalStore(db).list_trades(user_id)
              if (not mine_brokers or t.get("broker") in mine_brokers)
              and instrument_kind(t["symbol"], t.get("exchange")) == "STOCK"]
    closed = [t for t in build_round_trips(trades)
              if t.get("pnl") is not None and (_aware(t.get("closed_at")) or since) >= since]
    ids = {i for trip in closed for i in trip["trade_ids"]}
    mine_charges = mirror.costs([t for t in trades if t["_id"] in ids], closed, 0)["charges"]
    mine = sum(t["pnl"] for t in closed) - mine_charges
    ai = ai_charges = 0.0
    query = ai_book_query(user_id)
    if picks_only:
        query = {"$and": [query, {"strategy": {"$regex": "^picks:"}}]}
    async for t in db["paper_trades"].find(query):
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
    """You vs the AI: the user's account against the whole AI book (Picks, engine and news trades),
    closed and net of charges, today and this month. It counted only trades credited to a pick, so the
    AI's engine losses never showed against you."""
    return {"today": await pnl_since(db, user_id, roles, day_start(now)),
            "month": await pnl_since(db, user_id, roles, month_start(now))}


# ------------------------------------------------------------------ Telegram


def _rupees(value: Optional[float], sign: bool = False) -> str:
    if value is None:
        return "—"
    return f"{'+' if sign and value > 0 else '−' if value < 0 else ''}₹{abs(value):,.0f}"


def _pct(value: Optional[float]) -> str:
    return "" if value is None else f" ({value:+.1f}%)"


TOP_ACTIONS = 3


def _action_lines(actions: list[dict]) -> list[str]:
    """The top of Mine's "Needs you" list (mine/actions.py)."""
    if not actions:
        return []
    return [f"Needs you ({len(actions)}):"] + [f"• {escape(a['title'])}" for a in actions[:TOP_ACTIONS]]


def premarket_text(p: Optional[dict], overnight: dict[str, dict], ideas: Optional[int], ai: dict,
                   yesterday: Optional[dict] = None, actions: Optional[list[dict]] = None) -> str:
    lines = ["☀️ <b>Before the open</b>"]
    if p:
        moved = f", yesterday {_rupees(yesterday['change'], True)}{_pct(yesterday['pct'])}" if yesterday else ""
        lines.append(f"Your account: {_rupees(p['value'])}{moved}")
    lines += _action_lines(actions or [])
    if overnight:
        lines.append("News on your holdings since the close:")
        lines += [f"• {escape(sym)}: {escape(n['title'] or '')}" for sym, n in list(overnight.items())[:5]]
    else:
        lines.append("No material news on your holdings since the close.")
    if ideas is not None:  # None: not an admin, engine ideas are admin-only
        lines.append(f"Ideas for your account: {ideas}" if ideas else
                     "No ideas for your account: no strategy has earned it yet.")
    mode = "off" if not ai.get("enabled") else ("live" if ai.get("live") else "paper")
    lines.append(f"AI account: autopilot {mode}, {_rupees(ai.get('deployed'))} deployed.")
    return "\n".join(lines)


def news_why(m: dict) -> str:
    """One news move's reason: the headline, else whether it simply followed NIFTY."""
    if m.get("cause"):
        return m["cause"].get("title") or ""
    from backend.portfolio.news_moves import BIG_PCT

    vs = m.get("vs_nifty")
    return "moved with the market" if vs is not None and abs(vs) < BIG_PCT else "no news found"


def postclose_text(p: Optional[dict], today: dict, events: list[dict], actions: Optional[list[dict]] = None,
                   recon: Optional[str] = None) -> str:
    actions = actions or []
    # A worsened verdict already listed as an action is not repeated below.
    listed = {a["symbol"] for a in actions[:TOP_ACTIONS] if a["kind"] == "verdict_worse"}
    lines = ["🔔 <b>After the close</b>"]
    if p:
        lines.append(f"Your account: {_rupees(p['value'])}, today {_rupees(p['day_change'], True)}{_pct(p['day_change_pct'])}, "
                     f"overall {_rupees(p['pnl'], True)}{_pct(p['pnl_pct'])}")
        if p.get("news_moves"):  # what news moved your money (portfolio/news_moves.py), biggest rupees first
            lines.append("What moved your money:")
            for m in p["news_moves"][:MOVERS]:
                lines.append(f"• {escape(m['symbol'])} {m['move_pct']:+.1f}% — {escape(news_why(m))}")
        elif p["movers"]:
            lines.append("Moved most:")
            for m in p["movers"]:
                why = f" — {escape(m['why']['title'])}" if m.get("why") and m["why"].get("title") else ""
                lines.append(f"• {escape(m['symbol'])} {m['move_pct']:+.1f}%{why}")
        for c in p["verdict_changes"]:
            if c["symbol"] not in listed:
                lines.append(f"⚠️ {escape(c['symbol'])}: {c['from']} → {c['to']}")
    lines += _action_lines(actions)
    lines.append(f"Closed today, net: you {_rupees(today['mine'], True)} · AI {_rupees(today['ai'], True)}")
    if recon:  # only when the broker and the app's records disagree (engine/broker_recon.py)
        lines.append(f"⚠️ Reconciliation: {escape(recon)}")
    if events:
        lines.append("Tomorrow: " + "; ".join(escape(e.get("event") or e.get("title") or "") for e in events[:3]))
    return "\n".join(lines)


async def _ai_line(db, user_id: str, prefs: dict) -> dict:
    from backend.autopilot.service import open_trades

    deployed = sum((t.get("quantity") or 0) * (t.get("entry_price") or 0) for t in await open_trades(db, user_id))
    return {"enabled": prefs.get("autopilot_enabled"), "live": prefs.get("autopilot_live"), "deployed": deployed}


async def _actions(db, user_id: str, now: datetime) -> list[dict]:
    """The digest still goes without them if building the list fails."""
    from backend.mine import actions

    try:
        return await actions.build(db, user_id, now, await verdicts_visible(db, user_id))
    except Exception as exc:
        logger.warning("digest: actions failed for %s: %s", user_id, exc)
        return []


async def _users(db) -> list[str]:
    return sorted(set(await db["portfolio_snapshots"].distinct("user_id")) | set(
        await db["user_prefs"].distinct("user_id", {"broker_roles": {"$exists": True, "$ne": {}}})))


async def premarket_for(db, user_id: str, now: datetime) -> str:
    from backend.core.market_calendar import previous_trading_day
    from backend.portfolio.service import mine_holdings
    from backend.prefs import PrefsStore
    from backend.risk.paper_gate import for_mine

    local = now.astimezone(IST)
    prefs = await PrefsStore(db).get(user_id)
    p = await cached_pulse(db, user_id, now)
    held = list(await mine_holdings(db, user_id))
    # The previous session's close: on a Monday, Friday's (weekend news counts).
    last_close = datetime.combine(previous_trading_day(local.date()), time(15, 30), tzinfo=IST)
    overnight = await headlines_for(db, held, last_close)
    from backend.suggestions.notify import is_admin

    ideas = len(await for_mine(db, user_id, await db["suggestions"].find(
        {"user_id": user_id, "status": "PENDING", "mode": "LONGTERM"}).to_list(length=200))) if await is_admin(db, user_id) else None
    moved = await last_session_move(db, await mine_holdings(db, user_id), local.date())
    acts = await _actions(db, user_id, now)
    return premarket_text(p, overnight, ideas, await _ai_line(db, user_id, prefs), moved, acts)


async def postclose_for(db, user_id: str, now: datetime, events: Optional[list[dict]] = None,
                        actions: Optional[list[dict]] = None) -> str:
    """`actions`: Mine's list when the caller already built it (Today does)."""
    from backend.datalayer import market
    from backend.engine import broker_recon
    from backend.prefs import PrefsStore

    if events is None:
        events = await market.upcoming(db, hours=24, now=now)
    roles = (await PrefsStore(db).get(user_id)).get("broker_roles") or {}
    # weekend/holiday ("closed" phase): the last session's day, not today's empty one
    day = last_trading_day(now.astimezone(IST).date())
    recon = broker_recon.summary(await broker_recon.latest(db, user_id, day))
    return postclose_text(await cached_pulse(db, user_id, now),
                          await pnl_since(db, user_id, roles, datetime.combine(day, time(0, 0), tzinfo=IST)),
                          events, actions if actions is not None else await _actions(db, user_id, now), recon)


async def send_premarket(db, redis, now: datetime) -> int:
    """Weekdays 08:45-09:15 IST, once a day per user."""
    from backend.suggestions.notify import notify

    local = now.astimezone(IST)
    if not is_trading_day(local.date()) or not (PREMARKET <= local.time() < PREMARKET_END):
        return 0
    sent = 0
    for user_id in await _users(db):
        if not await redis.set(f"digest:pre:{user_id}:{local.date()}", "1", nx=True, px=86_400_000):
            continue
        try:
            text = await premarket_for(db, user_id, now)
            await notify(db, user_id, text, html=True)
            sent += 1
            await _day_summary(db, redis, user_id, "pre", now, text)
        except Exception as exc:
            logger.exception("pre-market digest failed for %s: %s", user_id, exc)
            await redis.delete(f"digest:pre:{user_id}:{local.date()}")  # let the next tick retry
    return sent


async def _day_summary(db, redis, user_id: str, phase: str, now: datetime, text: str) -> None:
    """Home's AI "Your day" (summaries/day.py); the digest has gone out either way."""
    from backend.summaries import day

    try:
        await day.generate(db, redis, user_id, phase, now, text)
    except Exception as exc:
        logger.warning("day summary failed for %s: %s", user_id, exc)


async def send_postclose(db, now: datetime, redis=None) -> int:
    """After the 16:00 pass's review (backend/scheduler.py). Skipped when the
    pass runs as the next morning's catch-up: an evening message at 9 AM is noise."""
    from backend.datalayer import market
    from backend.suggestions.notify import notify

    if now.astimezone(IST).time() < time(15, 30):
        return 0
    events = await market.upcoming(db, hours=24, now=now)
    sent = 0
    for user_id in await _users(db):
        try:
            text = await postclose_for(db, user_id, now, events)
            await notify(db, user_id, text, html=True)
            sent += 1
            await _day_summary(db, redis, user_id, "post", now, text)
        except Exception as exc:
            logger.exception("post-close digest failed for %s: %s", user_id, exc)
    return sent
