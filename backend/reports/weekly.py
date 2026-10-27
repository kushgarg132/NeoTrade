"""The weekly report: last ISO week for the user's own account against NIFTY,
the AI book, the ideas taken against skipped, and the journal. Built once here;
the page shows the dict and Telegram sends `text()` of the same dict."""

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from typing import Optional

from backend.engine.session import IST

logger = logging.getLogger(__name__)

SEND_AT, TTL_MS = time(18, 0), 8 * 86_400_000
TAKEN, SKIPPED = {"APPROVED", "EXECUTED"}, {"REJECTED", "EXPIRED"}
_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def parse_week(week: str) -> date:
    """'2026-W42' -> that week's Monday. ValueError on anything else."""
    m = _WEEK.match(week or "")
    if not m:
        raise ValueError(f"bad week {week!r}, want YYYY-Www")
    return date.fromisocalendar(int(m[1]), int(m[2]), 1)


def week_id(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def last_completed(today: date) -> str:
    """This week once it is Sunday, otherwise the one before."""
    return week_id(today if today.weekday() == 6 else today - timedelta(days=today.weekday() + 1))


def _bounds(monday: date) -> tuple[datetime, datetime]:
    start = datetime.combine(monday, time(0, 0), tzinfo=IST)
    return start, start + timedelta(days=7)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _in(dt, start, end) -> bool:
    dt = _aware(dt)
    return dt is not None and start <= dt < end


async def _returns(db, user_id: str, monday: date) -> dict:
    """Weekly return of the account and of NIFTY on the same rupees, from the
    mine_daily curve: (end - base - flows) / base, base the last day before the week."""
    from backend.mine import history

    rows = await history.series(db, user_id, monday - timedelta(days=10))
    end_day = (monday + timedelta(days=7)).isoformat()
    base = [r for r in rows if r["date"] < monday.isoformat()]
    week = [r for r in rows if monday.isoformat() <= r["date"] < end_day]
    if not base or not week or not base[-1]["value"]:
        return {"ret": None, "nifty": None, "excess": None}
    b, flows = base[-1], sum(r["flow"] for r in week)
    ret = (week[-1]["value"] - b["value"] - flows) / b["value"]
    nifty = (week[-1]["nifty_value"] - b["nifty_value"] - flows) / b["nifty_value"] if b["nifty_value"] else None
    return {"ret": ret, "nifty": nifty, "excess": ret - nifty if nifty is not None else None}


async def _journal(db, user_id: str, roles: dict, start, end) -> tuple[dict, list[dict]]:
    from backend.brokers.roles import brokers_for
    from backend.journal import mirror
    from backend.journal.roundtrips import build_round_trips
    from backend.journal.store import JournalStore

    mine = brokers_for(roles, "mine")
    trades = [t for t in await JournalStore(db).list_trades(user_id) if not mine or t.get("broker") in mine]
    closed = [t for t in build_round_trips(trades)
              if t.get("pnl") is not None and _in(t.get("closed_at"), start, end)]
    ids = {i for trip in closed for i in trip["trade_ids"]}
    charges = mirror.costs([t for t in trades if t["_id"] in ids], closed, 0)["charges"]
    net = round(sum(t["pnl"] for t in closed) - charges, 2)
    return {"trades": len(closed), "net": net, "charges": round(charges, 2)}, closed


def _extremes(closed: list[dict]) -> tuple[list[dict], list[dict]]:
    by_symbol: dict[str, float] = {}
    for t in closed:
        by_symbol[t["symbol"]] = by_symbol.get(t["symbol"], 0.0) + t["pnl"]
    rows = [{"symbol": s, "pnl": round(p, 2)} for s, p in by_symbol.items()]
    best = sorted((r for r in rows if r["pnl"] > 0), key=lambda r: -r["pnl"])[:3]
    worst = sorted((r for r in rows if r["pnl"] < 0), key=lambda r: r["pnl"])[:3]
    return best, worst


async def _ai(db, user_id: str, capital: float, start, end) -> dict:
    """The AI book's week, whole and per strategy (trades closed this week, net of costs; worst first), and
    `vs_nifty`: that net minus what the same rupees made in NIFTY over each trade's own days."""
    from backend.analytics import nifty_same_money
    from backend.autopilot.service import ai_book_query
    from backend.datalayer import bars

    pnl, by, closed = 0.0, {}, []
    async for t in db["paper_trades"].find(ai_book_query(user_id)):
        if t.get("status") == "CLOSED" and _in(t.get("exit_at"), start, end):
            net = (t.get("realized_pnl") or 0.0) - (t.get("costs") or 0.0)
            pnl += net
            closed.append(t)
            by.setdefault(t.get("strategy") or "unattributed", []).append(net)
    strategies = sorted(({"strategy": k, "n": len(v), "net": round(sum(v), 2), "wins": sum(x > 0 for x in v)}
                         for k, v in by.items()), key=lambda r: r["net"])
    vs = None
    if closed:
        since = min((_aware(t["entry_at"]).astimezone(IST).date() for t in closed if t.get("entry_at")), default=start.date()) - timedelta(days=7)
        points = [{"date": d.isoformat(), "close": c} for d, c in await bars.nifty_closes(db, since)]
        vs = round(pnl - sum(nifty_same_money(closed, points).values()), 2) if points else None
    return {"ret": pnl / capital if capital else None, "strategies": strategies, "vs_nifty": vs}


async def _grades(db, start, end) -> list[dict]:
    """Forward picks that matured this week, per grade (the setup's grade now, `picks.setup_grades`):
    count, mean excess over NIFTY, share that beat it. Backfilled picks are not forward picks."""
    from backend.forecast import picks

    grades = picks.setup_grades(await db[picks.STUDY].find_one({"_id": "latest"}))
    by: dict[str, list[dict]] = {}
    async for p in db[picks.PICKS].find({"scored_at": {"$gte": start, "$lt": end}, "backfilled": {"$ne": True}}):
        if p.get("outcome"):
            by.setdefault(grades.get(p["setup"], "C"), []).append(p["outcome"])
    return [{"grade": g, "n": len(os), "mean_excess": sum(o["net"] - o["nifty"] for o in os) / len(os),
             "beat": sum(o["beat_nifty"] for o in os) / len(os)} for g, os in sorted(by.items())]


async def _ideas(db, user_id: str, start, end) -> dict:
    """Scored forward records decided this week, split by what the user did with
    the suggestion (same symbol, same IST day)."""
    status = {}
    async for s in db["suggestions"].find({"user_id": user_id, "created_at": {"$gte": start - timedelta(days=1), "$lt": end}}):
        status[(s["symbol"], _aware(s["created_at"]).astimezone(IST).date())] = s["status"]
    groups = {"taken": [], "skipped": []}
    async for r in db["forward_records"].find({"user_id": user_id, "source": {"$in": ["suggestion", "news"]},
                                               "outcome.excess": {"$exists": True}}):
        if not _in(r["decided_at"], start, end):
            continue
        st = status.get((r["symbol"], _aware(r["decided_at"]).astimezone(IST).date()))
        key = "taken" if st in TAKEN else "skipped" if st in SKIPPED else None
        if key:
            groups[key].append(r["outcome"]["excess"])
    return {k: {"n": len(v), "mean_excess": sum(v) / len(v) if v else None} for k, v in groups.items()}


async def build(db, user_id: str, week: str) -> dict:
    from backend.prefs import PrefsStore
    from backend.suggestions.notify import is_admin

    start, end = _bounds(parse_week(week))
    prefs = await PrefsStore(db).get(user_id)
    journal, closed = await _journal(db, user_id, prefs.get("broker_roles") or {}, start, end)
    best, worst = _extremes(closed)
    from backend.portfolio import news_moves

    try:  # display and narrative context only: the report goes without it
        news = await news_moves.week(db, user_id, start, end)
    except Exception as exc:
        logger.warning("weekly report: news attribution failed for %s: %s", user_id, exc)
        news = {"movers": [], "themes": [], "accuracy": None}
    return {"week": week, "you": await _returns(db, user_id, start.date()),
            "ai": await _ai(db, user_id, prefs.get("account_size") or 0, start, end),
            "best": best, "worst": worst, "ideas": await _ideas(db, user_id, start, end), "journal": journal,
            "news": news, "grades": await _grades(db, start, end) if await is_admin(db, user_id) else []}


# ------------------------------------------------------------------ Telegram


def _p(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:+.2f}%"


def _r(x: float) -> str:
    return f"{'-' if x < 0 else '+' if x > 0 else ''}₹{abs(round(x)):,}"


def text(r: dict, narrative: Optional[str] = None) -> str:
    you, ai, ideas, j = r["you"], r["ai"], r["ideas"], r["journal"]
    lines = [f"<b>Your week {escape(r['week'])}</b>",
             f"You {_p(you['ret'])} · NIFTY {_p(you['nifty'])} · excess {_p(you['excess'])}",
             f"AI book {_p(ai['ret'])}" + (f" · vs the same money in NIFTY {_r(ai['vs_nifty'])}" if ai.get("vs_nifty") is not None else "")]
    if ai.get("strategies"):
        lines.append("AI by strategy: " + ", ".join(
            f"{escape(x['strategy'])} {_r(x['net'])} ({x['wins']}/{x['n']} won)" for x in ai["strategies"]))
    if r.get("grades"):  # admins only: Picks are not shown to anyone else
        lines.append("Picks matured: " + ", ".join(
            f"{g['grade']} {g['n']} ({_p(g['mean_excess'])} vs NIFTY, {g['beat']:.0%} beat)" for g in r["grades"]))
    for label, rows in (("Best", r["best"]), ("Worst", r["worst"])):
        if rows:
            lines.append(f"{label}: " + ", ".join(f"{escape(x['symbol'])} {_r(x['pnl'])}" for x in rows))
    for key in ("taken", "skipped"):
        g = ideas[key]
        lines.append(f"Ideas {key}: {g['n']}" + (f" ({_p(g['mean_excess'])} vs NIFTY)" if g["n"] else ""))
    moved = (r.get("news") or {}).get("movers") or []
    if moved:
        lines.append("News behind big moves: " + "; ".join(
            f"{escape(m['symbol'])} {m['move_pct']:+.1f}%" + (f" ({escape(m['items'][0]['title'] or '')})" if m["items"] else "")
            for m in moved[:3]))
    lines.append(f"Journal: {j['trades']} trades, net {_r(j['net'])} after {_r(j['charges'])[1:]} charges")
    if narrative:  # the AI's paragraph (summaries/weekly.py), closing the message
        lines += ["", escape(narrative)]
    return "\n".join(lines)


async def send(db, redis, now: datetime) -> int:
    """Sundays from 18:00 IST, once per user per ISO week (Redis NX, 8 days)."""
    from backend.portfolio.digest import _users
    from backend.suggestions.notify import notify

    local = now.astimezone(IST)
    if local.weekday() != 6 or local.time() < SEND_AT:
        return 0
    week, sent = last_completed(local.date()), 0
    for user_id in await _users(db):
        key = f"report:weekly:{user_id}:{week}"
        if not await redis.set(key, "1", nx=True, px=TTL_MS):
            continue
        try:
            report = await build(db, user_id, week)
            from backend.summaries import weekly as narrative

            written = await narrative.generate(db, redis, user_id, report)  # None: keep the numbers-only text
            await notify(db, user_id, text(report, written and written["text"]), html=True)
            sent += 1
        except Exception as exc:
            logger.exception("weekly report failed for %s: %s", user_id, exc)
            await redis.delete(key)
    return sent
