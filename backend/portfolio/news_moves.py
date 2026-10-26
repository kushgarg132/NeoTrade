"""What news moved your money (news plan N1.5, display only): each big move in
the user's own holdings today matched to the strongest material scored item
about the stock or its sector since the previous close, else null ("moved with
the market" / "no news found"). Also the weekly report's news attribution
(N1.6): big weekly movers, the themes that hit the book, and the latest news
accuracy line. Reads what the news engine already stores; no LLM call."""

import logging
from datetime import datetime, time, timezone
from typing import Optional

from backend.strategies.longterm.analyst_verdict import MATERIALITY_THRESHOLD

logger = logging.getLogger(__name__)

BIG_PCT = 2.0        # day move vs NIFTY that counts as big
TOP_RUPEES = 3       # the biggest rupee movers are always explained
WEEK_BIG_PCT = 4.0   # weekly move vs NIFTY that counts as big
WEEK_ITEMS, THEMES = 2, 5
SCOPES = {"symbol": "COMPANY", "sector": "SECTOR"}


def _aware(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


def big_moves(rows: list[dict], nifty_pct: Optional[float], big: float = BIG_PCT, top: int = TOP_RUPEES) -> list[dict]:
    """rows [{symbol, move_pct, rupees}] -> the ones beyond ±`big` against NIFTY (the raw move when
    NIFTY is unknown) or among the `top` absolute rupee movers, biggest rupees first, with `vs_nifty`."""
    by_rupees = sorted((r for r in rows if r.get("move_pct") is not None), key=lambda r: -abs(r.get("rupees") or 0))
    out = []
    for i, r in enumerate(by_rupees):
        vs = r["move_pct"] - nifty_pct if nifty_pct is not None else None
        if i < top or abs(vs if vs is not None else r["move_pct"]) >= big:
            out.append({**r, "vs_nifty": None if vs is None else round(vs, 2)})
    return out


def causes(items: list[dict], symbol: str, sector: Optional[str], limit: int = 1) -> list[dict]:
    """The strongest material impacts on `symbol` (or its sector) among scored `items`: by impact, a
    company item ahead of a sector one on a tie; one per item."""
    found = []
    for item in items:
        best = None
        for imp in item.get("impacts") or []:
            hit = (imp.get("type") in ("symbol", None) and imp.get("target") == symbol) or \
                  (sector and imp.get("type") == "sector" and imp.get("target") == sector)
            if hit and (imp.get("impact") or 0) >= MATERIALITY_THRESHOLD:
                key = (imp.get("impact") or 0, imp.get("type") != "sector")
                if best is None or key > best[0]:
                    best = (key, imp)
        if best:
            imp = best[1]
            found.append((best[0], {"title": item.get("event") or item.get("title"), "url": item.get("url"),
                                    "scope": SCOPES.get(imp.get("type"), "COMPANY"), "direction": imp.get("direction"),
                                    "impact": imp.get("impact"), "themes": item.get("themes") or []}))
    found.sort(key=lambda f: f[0], reverse=True)
    return [c for _, c in found[:limit]]


def attribute(rows: list[dict], nifty_pct: Optional[float], items: list[dict], sector_of: dict) -> list[dict]:
    """The Today list: [{symbol, move_pct, vs_nifty, rupees, cause | None}]."""
    out = []
    for r in big_moves(rows, nifty_pct):
        found = causes(items, r["symbol"], sector_of.get(r["symbol"]))
        cause = {k: v for k, v in found[0].items() if k != "themes"} if found else None
        out.append({"symbol": r["symbol"], "move_pct": round(r["move_pct"], 2), "vs_nifty": r["vs_nifty"],
                    "rupees": round(r.get("rupees") or 0, 2), "cause": cause})
    return out


def themes(items: list[dict], held: set[str], sector_of: dict, top: int = THEMES) -> list[dict]:
    """Themes of the material items that touched a held name or its sector: count, summed impact
    and mean direction, heaviest first."""
    sectors = {sector_of[s] for s in held if sector_of.get(s)}
    agg: dict[str, list] = {}
    for item in items:
        hits = [i for i in item.get("impacts") or [] if (i.get("impact") or 0) >= MATERIALITY_THRESHOLD and (
            (i.get("type") in ("symbol", None) and i.get("target") in held) or
            (i.get("type") == "sector" and i.get("target") in sectors))]
        if not hits:
            continue
        strongest = max(hits, key=lambda i: i.get("impact") or 0)
        for theme in item.get("themes") or []:
            a = agg.setdefault(theme, [0, 0.0, 0.0])
            a[0] += 1
            a[1] += strongest.get("impact") or 0
            a[2] += strongest.get("direction") or 0
    rows = [{"theme": t, "n": n, "impact": round(imp, 1), "direction": round(d / n, 2)} for t, (n, imp, d) in agg.items()]
    return sorted(rows, key=lambda r: -r["impact"])[:top]


def accuracy_line(doc: Optional[dict]) -> Optional[dict]:
    """5-day COMPANY and SECTOR hit rates (percent) from a `news_accuracy` report, or None.
    An excess-vs-NIFTY measure is preferred when the report has several."""
    if not doc:
        return None
    out = {}
    for scope in ("COMPANY", "SECTOR"):
        cells = [c for c in doc.get("cells") or [] if str(c.get("scope", "")).upper() == scope
                 and str(c.get("horizon", "")).lower() == "5d" and c.get("hit") is not None]
        cells.sort(key=lambda c: "excess" not in str(c.get("measure", "")).lower())
        if cells:
            hit = cells[0]["hit"]
            out[scope.lower()] = {"hit_pct": round(hit * 100 if hit <= 1 else hit, 1), "n": cells[0].get("n")}
    return out or None


async def _items(db, targets: list[str], since: datetime, until: Optional[datetime] = None) -> list[dict]:
    window = {"$gte": since, **({"$lt": until} if until else {})}
    return await db["news_items"].find(
        {"published_at": window, "status": "SCORED", "material": True, "impacts.target": {"$in": targets}},
        {"title": 1, "event": 1, "url": 1, "themes": 1, "impacts": 1}).sort("published_at", -1).to_list(length=500)


async def _nifty_day_pct() -> Optional[float]:
    """NIFTY's move today from the ingest worker's macro feed; None when it has none."""
    from backend.database import db as handle
    from backend.datalayer.prices import macro_rows

    rows = await macro_rows(handle.redis, {"NIFTY 50": "^NSEI"})
    return rows[0].get("percent") if rows else None


async def today(db, rows: list[dict], now: datetime) -> list[dict]:
    """`attribute` over `rows` (the user's own stock holdings) with news since the last session's
    previous close: on a weekend that is Thursday's close, so Friday's news still counts."""
    from backend.core.market_calendar import last_trading_day, previous_trading_day
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.engine.session import IST

    if not rows:
        return []
    session = last_trading_day(now.astimezone(IST).date())
    since = datetime.combine(previous_trading_day(session), time(15, 30), tzinfo=IST)
    sector_of = nifty200_sectors()
    symbols = [r["symbol"] for r in rows]
    targets = symbols + sorted({sector_of[s] for s in symbols if s in sector_of})
    try:
        nifty = await _nifty_day_pct()
    except Exception as exc:
        logger.warning("news moves: NIFTY move unavailable: %s", exc)
        nifty = None
    return attribute(rows, nifty, await _items(db, targets, since), sector_of)


async def week(db, user_id: str, start: datetime, end: datetime) -> dict:
    """The weekly report's news part: held names that moved big against NIFTY over the week with the
    items behind them, the themes that hit the book, and the latest 5-day accuracy line."""
    from backend.datalayer import bars
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.portfolio.service import mine_holdings

    held = sorted(await mine_holdings(db, user_id))
    sector_of = nifty200_sectors()
    movers = []
    if held:
        names = [*held, bars.NIFTY]
        base = await bars.prev_closes(db, names, start.date())
        last = await bars.prev_closes(db, names, end.date())
        nifty = (last[bars.NIFTY] / base[bars.NIFTY] - 1) * 100 if base.get(bars.NIFTY) and bars.NIFTY in last else None
        rows = [{"symbol": s, "move_pct": (last[s] / base[s] - 1) * 100} for s in held if base.get(s) and s in last]
        targets = held + sorted({sector_of[s] for s in held if s in sector_of})
        items = await _items(db, targets, start, end)
        for r in big_moves(rows, nifty, WEEK_BIG_PCT, top=0):
            found = causes(items, r["symbol"], sector_of.get(r["symbol"]), WEEK_ITEMS)
            movers.append({"symbol": r["symbol"], "move_pct": round(r["move_pct"], 2), "vs_nifty": r["vs_nifty"],
                           "items": [{k: v for k, v in c.items() if k != "themes"} for c in found]})
        movers.sort(key=lambda m: -abs(m["vs_nifty"] if m["vs_nifty"] is not None else m["move_pct"]))
        hit = themes(items, set(held), sector_of)
    else:
        hit = []
    doc = await db["news_accuracy"].find_one({}, sort=[("at", -1), ("_id", -1)])
    return {"movers": movers, "themes": hit, "accuracy": accuracy_line(doc)}
