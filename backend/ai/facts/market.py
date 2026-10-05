"""Market facts: prices, fundamentals, news, sentiment, backdrop, calendar."""

import json
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from backend.ai.facts import fact

NEWS_MAX, NEWS_MAX_HOURS = 30, 24 * 60


def _bare(symbol: str) -> str:
    return symbol.strip().upper().removesuffix(".NS")


def _r(x, n=2):
    return None if x is None or x != x else round(float(x), n)


@fact("quote", "Latest price of an NSE stock (last traded or last close), with its time.", source="quote cache")
async def quote(db, redis, user_id, symbol: str) -> dict:
    from backend.marks import mark_prices

    symbol = _bare(symbol)
    price = (await mark_prices(db, [symbol])).get(symbol)
    return {"symbol": symbol, "price": _r(price)} if price else {"symbol": symbol, "error": "no price available"}


@fact("price_summary", "Price history summary of an NSE stock from daily bars: last close, 1/5/20/60-day % "
      "returns, 52-week high/low, 20/50/200-day averages, 14-day ATR.", source="daily_bars")
async def price_summary(db, redis, user_id, symbol: str, days: int = 60) -> dict:
    from backend.datalayer import bars

    symbol = _bare(symbol)
    frame = (await bars.read(db, [symbol], bars.today_ist() - timedelta(days=400))).get(symbol)
    if frame is None or frame.empty:
        return {"symbol": symbol, "error": "no daily bars"}
    close = frame["close"]
    last = float(close.iloc[-1])

    def ret(n):
        return _r((last / float(close.iloc[-1 - n]) - 1) * 100) if len(close) > n else None

    def sma(n):
        return _r(close.tail(n).mean()) if len(close) >= n else None

    true_range = (frame["high"] - frame["low"]).tail(14)
    year = frame.tail(252)
    return {"symbol": symbol, "date": frame.index[-1].date().isoformat(), "last_close": _r(last),
            "ret_1d": ret(1), "ret_5d": ret(5), "ret_20d": ret(20), "ret_60d": ret(60),
            "high_52w": _r(year["high"].max()), "low_52w": _r(year["low"].min()),
            "sma_20": sma(20), "sma_50": sma(50), "sma_200": sma(200), "atr_14": _r(true_range.mean()),
            "bars": int(len(frame))}


@fact("fundamentals", "Stored fundamentals of an NSE stock (valuation, growth, margins, debt).", source="fundamentals")
async def fundamentals(db, redis, user_id, symbol: str) -> dict:
    from backend.datalayer import bars

    symbol = _bare(symbol)
    doc = await db[bars.FUNDAMENTALS].find_one({"_id": symbol})
    if not doc:
        return {"symbol": symbol, "error": "no stored fundamentals"}
    return {"symbol": symbol, **{k: v for k, v in doc.items() if k != "_id"}}


@fact("news", "Scored market news: by stock symbol, NSE sector, scope (COMPANY/SECTOR/MARKET/MACRO/GLOBAL) or "
      "words in the headline; each item with its impact (direction -1..1, impact 0-10) on the asked target.",
      source="news_items")
async def news(db, redis, user_id, symbol: Optional[str] = None, sector: Optional[str] = None,
               scope: Optional[Literal["COMPANY", "SECTOR", "MARKET", "MACRO", "GLOBAL"]] = None,
               query: Optional[str] = None, hours: int = 48, material_only: bool = False, limit: int = 10) -> dict:
    import re

    from backend.datalayer.news import COLLECTION, SCORED

    hours, limit = max(1, min(int(hours), NEWS_MAX_HOURS)), max(1, min(int(limit), NEWS_MAX))
    target = _bare(symbol) if symbol else sector
    conditions: list[dict] = [{"status": SCORED},
                              {"published_at": {"$gte": datetime.now(timezone.utc) - timedelta(hours=hours)}}]
    if symbol:
        conditions.append({"$or": [{"symbols": target}, {"impacts.target": target}]})
    if sector:
        conditions.append({"impacts.target": sector})
    if scope:
        conditions.append({"scope": scope})
    if query:
        conditions.append({"title": {"$regex": re.escape(query), "$options": "i"}})
    if material_only:
        conditions.append({"material": True})
    rows = await db[COLLECTION].find({"$and": conditions}, {
        "_id": 0, "title": 1, "source": 1, "published_at": 1, "scope": 1, "event": 1, "impacts": 1, "url": 1,
        "material": 1}).sort("published_at", -1).limit(limit).to_list(length=limit)
    for row in rows:
        if target:
            row["impacts"] = [i for i in row.get("impacts") or [] if i.get("target") == target]
    return {"count": len(rows), "items": rows}


@fact("sentiment", "News sentiment (-1..1) for a stock, its sector and the Indian market.", source="sentiment cache")
async def sentiment(db, redis, user_id, symbol: str) -> dict:
    from backend.datalayer.news_sources import nifty200_sectors

    symbol = _bare(symbol)
    sector = nifty200_sectors().get(symbol)
    stock, sect, mkt = await redis.mget([f"sentiment:{symbol}", f"sector_sentiment:{sector}", "market:sentiment"])

    def score(raw):
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return _r(value.get("score") if isinstance(value, dict) else value)
    return {"symbol": symbol, "stock": score(stock), "sector": sector, "sector_score": score(sect),
            "market": score(mkt)}


@fact("market_backdrop", "The Indian market right now: AI brief, rule-based regime (risk_on/neutral/risk_off and "
      "why), indices/futures/crude/gold/USDINR/US10Y, FII/DII flows, news sentiment per NSE sector.",
      source="datalayer")
async def market_backdrop(db, redis, user_id) -> dict:
    from backend.datalayer.market import FLOWS_KEY, backdrop
    from backend.datalayer.prices import MACRO, macro_rows

    from backend.datalayer.news_sources import sectors

    context = await backdrop(redis)
    flows = await redis.get(FLOWS_KEY) if redis is not None else None
    names = sectors()
    raws = await redis.mget([f"sector_sentiment:{s}" for s in names]) if redis is not None else []
    sector_scores = {s: round(json.loads(r)["score"], 2) for s, r in zip(names, raws)
                     if r and json.loads(r).get("score") is not None}
    return {"brief": context.get("brief"), "regime": context.get("regime"),
            "markets": await macro_rows(redis, MACRO), "flows": json.loads(flows) if flows else None,
            "sector_news_sentiment": sector_scores}


@fact("calendar", "Economic calendar for the next hours (time, country, title, impact); high-impact only unless "
      "high_only is false.", source="econ_calendar")
async def calendar(db, redis, user_id, hours: int = 48, high_only: bool = True) -> dict:
    from backend.datalayer.market import upcoming

    events = await upcoming(db, hours=max(1, min(int(hours), 7 * 24)), high_only=high_only)
    return {"events": [{"at": e["at"], "country": e.get("country"), "title": e.get("title"),
                        "impact": e.get("impact")} for e in events]}
