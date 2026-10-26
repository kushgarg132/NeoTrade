"""N0.5: years of news history to test news on, kept apart from the live pipeline.

    fetch     Google News searches by month (each Nifty 200 company, each
              sector, the market, macro) and NSE filings by year
              -> Mongo `news_history` (live `store`, so the same ids and tags)
    estimate  LLM calls and prompt tokens still needed for what is stored
    score     triage then score on the fast tier with the live prompts, at
              most --max-calls calls per run; resumable
    outcomes  scored impacts -> `news_history_outcomes`: excess vs Nifty (and
              vs sector peers) at 1, 5 and 20 trading days, from daily bars
    report    accuracy.report over them -> `news_accuracy` {_id: "history"}

Its own collections, so live triage, theme weights and the N0.1 gate never
read it. Google gives only the publication day, and its headlines often
report that day's move, so a Google item's base is that day's close: the
reaction it reports is never counted as the news being right. NSE filings
carry a time: the base is the last close at or before it (outcomes._closes_at).
Caveat: the scoring model was trained after these dates and may know what
followed; a high hit rate here is an upper bound, not an edge.

    python -m backend.datalayer.backfill_news fetch 2024-10 2026-10
    python -m backend.datalayer.backfill_news estimate
    python -m backend.datalayer.backfill_news score --max-calls 200
    python -m backend.datalayer.backfill_news outcomes
    python -m backend.datalayer.backfill_news report
"""

import asyncio
import logging
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import pandas as pd
import requests

from backend.datalayer import accuracy, bars, news, news_sources
from backend.datalayer.outcomes import BENCH, CLOSE, _members, basket_return
from backend.engine.session import IST
from backend.prompts import render

logger = logging.getLogger(__name__)

ITEMS, OUTCOMES, DONE = "news_history", "news_history_outcomes", "news_history_fetch"
GOOGLE_PAUSE = 2.0  # seconds between Google searches; it 503s a fast client
NSE_PAUSE = 1.0
PARALLEL = 4  # LLM calls in flight
HORIZONS = {"1d": 1, "5d": 5, "20d": 20}  # trading days
# Rough answer sizes for the estimate: triage lists ~40% of headlines.
TRIAGE_OUT_PER_ITEM, SCORE_OUT_PER_ITEM = 8, 60
MARKET_QUERIES = {"gnews_india_market": ("Sensex Nifty stock market", "MARKET"),
                  "gnews_india_macro": ("RBI rupee crude oil FII markets", "MACRO")}


def _universe() -> tuple[dict[str, str], dict[str, str]]:
    rows = news_sources.universe_rows()
    return ({r["symbol"]: news.short_name(r["name"]) for r in rows}, {r["symbol"]: r["sector"] for r in rows})


def months(first: str, last: str) -> list[tuple[date, date]]:
    """'2024-10', '2024-12' -> [(Oct 1, Nov 1), (Nov 1, Dec 1), (Dec 1, Jan 1)]."""
    y, m = map(int, first.split("-"))
    end = tuple(map(int, last.split("-")))
    out = []
    while (y, m) <= end:
        nxt = (y + m // 12, m % 12 + 1)
        out.append((date(y, m, 1), date(*nxt, 1)))
        y, m = nxt
    return out


def _google(query: str, a: date, b: date) -> str:
    return news_sources.GOOGLE.format(q=quote_plus(f"{query} after:{a.isoformat()} before:{b.isoformat()}"))


def searches(span: list[tuple[date, date]], names: dict[str, str]) -> list[tuple[str, str, str, str, tuple]]:
    """(done key, url, feed, scope_hint, symbols) for every Google search."""
    out = []
    for a, b in span:
        tag = a.strftime("%Y-%m")
        for feed, (q, scope) in MARKET_QUERIES.items():
            out.append((f"{feed}:{tag}", _google(q, a, b), feed, scope, ()))
        for s in news_sources.sectors():
            out.append((f"sector:{s}:{tag}", _google(f'India "{s}" sector stocks', a, b), "gnews_sector", "SECTOR", ()))
        for symbol, name in names.items():
            out.append((f"sym:{symbol}:{tag}", _google(f'"{name}" share', a, b), "gnews_symbol", "COMPANY", (symbol,)))
    return out


def _get(session: requests.Session, url: str, **kw) -> requests.Response:
    """One retry after a minute on a throttle (429/503)."""
    for attempt in (1, 2):
        response = session.get(url, headers=news_sources.UA, timeout=30, **kw)
        if response.status_code not in (429, 503) or attempt == 2:
            response.raise_for_status()
            return response
        time.sleep(60)


async def fetch(db, first: str, last: str) -> int:
    names, _ = _universe()
    aliases = news.build_aliases(names)
    span = months(first, last)
    done = {d["_id"] async for d in db[DONE].find({}, {"_id": 1})}
    session, new = requests.Session(), 0

    async def keep(key: str, items: list[dict]) -> None:
        nonlocal new
        new += await news.store(db, items, aliases, names=names, coll=ITEMS)
        await db[DONE].insert_one({"_id": key, "n": len(items)})

    todo = [s for s in searches(span, names) if s[0] not in done]
    logger.info("news history: %d Google search(es) to run", len(todo))
    for n, (key, url, feed, scope, symbols) in enumerate(todo, 1):
        try:
            xml = (await asyncio.to_thread(_get, session, url)).content
            await keep(key, news_sources.parse_rss(xml, feed, scope, symbols, max_age=None))
        except Exception as exc:  # left undone: the next run retries it
            logger.warning("news history %s failed: %s", key, exc)
        if n % 100 == 0:
            logger.info("news history: %d/%d searches, %d new item(s)", n, len(todo), new)
        await asyncio.sleep(GOOGLE_PAUSE)

    # NSE wants its cookies first; the history API takes a symbol and a date range.
    await asyncio.to_thread(session.get, "https://www.nseindia.com/", headers=news_sources.UA, timeout=30)
    for year in sorted({a.year for a, _ in span}):
        lo, hi = max(span[0][0], date(year, 1, 1)), min(span[-1][1] - timedelta(days=1), date(year, 12, 31))
        for symbol in names:
            key = f"nse:{symbol}:{year}"
            if key in done:
                continue
            url = (f"{news_sources.NSE_ANNOUNCEMENTS}&symbol={quote_plus(symbol)}"
                   f"&from_date={lo:%d-%m-%Y}&to_date={hi:%d-%m-%Y}")
            try:
                rows = (await asyncio.to_thread(_get, session, url)).json()
                await keep(key, news_sources.parse_nse(rows if isinstance(rows, list) else [], {symbol}))
            except Exception as exc:
                logger.warning("news history %s failed: %s", key, exc)
            await asyncio.sleep(NSE_PAUSE)
    return new


# ------------------------------------------------------------------ LLM


def _triage_listing(docs: list[dict]) -> str:
    return "\n".join(f"[{i}] [{d['scope_hint']}] {d['title']} ({d['source']})" for i, d in enumerate(docs))


async def estimate(db) -> dict:
    """Calls and tokens (chars / 4) left: triage for NEW, scoring for TRIAGED
    plus the share of NEW that triage keeps (measured so far, else 40%)."""
    coll = db[ITEMS]
    new_n = await coll.count_documents({"status": news.NEW})
    triaged_n = await coll.count_documents({"status": news.TRIAGED})
    kept, dropped = (await coll.count_documents({"relevant": True, "feeds": {"$ne": "nse"}}),
                     await coll.count_documents({"status": news.IRRELEVANT}))
    keep = kept / (kept + dropped) if kept + dropped >= 500 else 0.4
    sample = await coll.find({"status": news.NEW}).limit(news.TRIAGE_BATCH).to_list(length=None)
    per_triage = len("".join(render("triage_news", items=_triage_listing(sample)))) / 4 if sample else 0
    score_items = triaged_n + new_n * keep
    sectors = ", ".join(news_sources.sectors())
    # A scored item is title + 400 chars of content + its tags: ~600 chars.
    per_score = len("".join(render("score_market_news", sectors=sectors, items=""))) / 4 + news.SCORE_BATCH * 150
    triage_calls, score_calls = math.ceil(new_n / news.TRIAGE_BATCH), math.ceil(score_items / news.SCORE_BATCH)
    return {
        "new": new_n, "triaged": triaged_n, "keep_rate": round(keep, 2),
        "triage_calls": triage_calls, "score_calls": score_calls,
        "input_tokens": int(triage_calls * per_triage + score_calls * per_score),
        "output_tokens": int(new_n * keep * TRIAGE_OUT_PER_ITEM + score_items * SCORE_OUT_PER_ITEM),
    }


def _day(at: datetime) -> date:
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(IST).date()


def prune(docs: list[dict]) -> list[tuple[dict, str]]:
    """news._skip_reason over TRIAGED docs, rewrites compared within the same IST day."""
    seen, out = defaultdict(list), []
    for doc in sorted(docs, key=lambda d: d["published_at"]):
        reason = news._skip_reason(doc, seen[_day(doc["published_at"])])
        if reason:
            out.append((doc, reason))
    return out


async def score(db, max_calls: int) -> dict:
    """Triage first (scoring needs triaged items), then score, both on the
    fast tier, PARALLEL calls at a time, until max_calls are spent."""
    names, sector_of = _universe()
    sectors = news_sources.sectors()
    coll, used = db[ITEMS], {"triage": 0, "score": 0}

    async def run(kind: str, batch_size: int, query: dict, call) -> None:
        while sum(used.values()) < max_calls:
            n = min(PARALLEL, max_calls - sum(used.values()))
            docs = await coll.find(query).sort("published_at", 1).limit(batch_size * n).to_list(length=None)
            if not docs:
                return
            now = datetime.now(timezone.utc)
            batches = [docs[i:i + batch_size] for i in range(0, len(docs), batch_size)]
            await asyncio.gather(*(call(b, now) for b in batches))
            used[kind] += len(batches)
            logger.info("news history %s: %d call(s) so far", kind, used[kind])
            if kind == "triage":
                await _prune(coll)

    # attempts < MAX keeps a batch the model keeps failing from looping: it goes FAILED.
    live = {"attempts": {"$lt": news.MAX_ATTEMPTS}}
    await run("triage", news.TRIAGE_BATCH, {"status": news.NEW, **live},
              lambda b, now: news._triage_batch(db, b, now, coll=ITEMS))
    await _prune(coll)
    await run("score", news.SCORE_BATCH, {"status": news.TRIAGED, **live},
              lambda b, now: news._score_batch(db, b, names, sector_of, sectors, now, coll=ITEMS, tier="fast"))
    return used


async def _prune(coll) -> None:
    docs = await coll.find({"status": news.TRIAGED, "pruned": {"$ne": True}},
                           {"title": 1, "scope": 1, "symbols": 1, "published_at": 1}).to_list(length=None)
    skip = prune(docs)
    for doc, reason in skip:
        await coll.update_one({"_id": doc["_id"]}, {"$set": {
            "status": news.IRRELEVANT, "relevant": False, "skip_reason": reason}})
    await coll.update_many({"_id": {"$in": [d["_id"] for d in docs]}, "status": news.TRIAGED},
                           {"$set": {"pruned": True}})


# ------------------------------------------------------------- outcomes


def base_day(doc: dict) -> date:
    """The close the news met: a filing's last close at or before its time;
    a Google item's own day (its reported move already happened)."""
    at = (doc["published_at"] if doc["published_at"].tzinfo else
          doc["published_at"].replace(tzinfo=timezone.utc)).astimezone(IST)
    if "nse" in (doc.get("feeds") or []) and at.time() < CLOSE:
        return at.date() - timedelta(days=1)
    return at.date()


def moves(closes: dict[str, pd.Series], calendar: pd.DatetimeIndex, kind: str, members: list[str],
          peers: list[str], day: date) -> dict:
    """move_{h} (excess vs Nifty) and, given peers, sector_move_{h} (vs them)
    at each horizon, in trading days of `calendar` (Nifty's) after `day`."""
    pos = calendar.searchsorted(pd.Timestamp(day), side="right") - 1
    if pos < 0:
        return {}
    start = calendar[pos]

    def at(symbols, when):
        return {s: float(closes[s].asof(when)) for s in symbols if s in closes and not pd.isna(closes[s].asof(when))}

    base, peer_base, bench = at(members, start), at(peers, start), closes[BENCH].asof(start)
    out = {}
    for h, n in HORIZONS.items():
        if pos + n >= len(calendar):
            continue
        end = calendar[pos + n]
        bench_ret = closes[BENCH].asof(end) / bench - 1
        if kind == "market":
            out[f"move_{h}"] = bench_ret
            continue
        own = basket_return(base, at(members, end))
        if own is None:
            continue
        out[f"move_{h}"] = own - bench_ret
        if peers:
            others = basket_return(peer_base, at(peers, end))
            if others is not None:
                out[f"sector_move_{h}"] = own - others
    return out


async def outcomes(db) -> int:
    _, sector_of = _universe()
    first = await db[ITEMS].find_one({"status": news.SCORED}, {"published_at": 1}, sort=[("published_at", 1)])
    if not first:
        return 0
    frames = await bars.read(db, [*sector_of, BENCH], _day(first["published_at"]) - timedelta(days=10))
    if BENCH not in frames:
        raise RuntimeError(f"no {BENCH} daily bars")
    closes = {s: f["close"] for s, f in frames.items()}
    calendar = closes[BENCH].index
    stored = 0
    async for doc in db[ITEMS].find({"status": news.SCORED, "impacts.0": {"$exists": True}}):
        day = base_day(doc)
        for i in doc["impacts"]:
            members = _members(i["type"], i["target"], sector_of)
            peers = [s for s, sec in sector_of.items() if sec == sector_of.get(i["target"]) and s != i["target"]] \
                if i["type"] == "symbol" else []
            fields = moves(closes, calendar, i["type"], members, peers, day)
            if not fields:
                continue
            await db[OUTCOMES].replace_one({"_id": f"{doc['_id']}:{i['type']}:{i['target']}"}, {
                "item_id": doc["_id"], "type": i["type"], "target": i["target"], "scope": doc.get("scope"),
                "themes": doc.get("themes") or [], "direction": i["direction"], "impact": i["impact"],
                "published_at": doc["published_at"], "base_day": day.isoformat(), "source": doc.get("source"),
                "model": doc.get("model"), **fields}, upsert=True)
            stored += 1
    return stored


async def report(db) -> dict:
    rows = await db[OUTCOMES].find({}).to_list(length=None)
    doc = {"as_of": datetime.now(timezone.utc), "rows": len(rows), "cells": accuracy.report(rows)}
    await db[accuracy.COLLECTION].replace_one({"_id": "history"}, doc, upsert=True)
    return doc


def summary(doc: dict) -> str:
    lines = [f"{doc['rows']} outcome(s)", "scope      horizon  n      hit   mean     t"]
    for c in doc["cells"]:
        if c["group"] == "theme" and c["key"] == "all" and c["impact"] == "all" and c["measure"] == "move":
            t = f"{c['t']:.1f}" if c["t"] is not None else "-"
            lines.append(f"{c['scope']:<10} {c['horizon']:<8} {c['n']:<6} {c['hit']:.0%}  {c['mean']:+.2%}  {t}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    from backend.database import db as _db

    parser = argparse.ArgumentParser(prog="python -m backend.datalayer.backfill_news")
    parser.add_argument("command", choices=["fetch", "estimate", "score", "outcomes", "report"])
    parser.add_argument("span", nargs="*", help="fetch: FIRST LAST months, e.g. 2024-10 2026-10")
    parser.add_argument("--max-calls", type=int, default=0, help="score: LLM calls this run (required)")
    args = parser.parse_args()

    async def _main() -> None:
        await _db.connect_to_database()
        db = _db.db
        if args.command == "fetch":
            if len(args.span) != 2:
                parser.error("fetch needs FIRST LAST months")
            print(f"fetched {await fetch(db, *args.span)} new item(s)")
        elif args.command == "estimate":
            print(await estimate(db))
        elif args.command == "score":
            if args.max_calls <= 0:
                parser.error("score needs --max-calls N (run estimate first)")
            print(await score(db, args.max_calls))
        elif args.command == "outcomes":
            print(f"stored {await outcomes(db)} outcome(s)")
        else:
            print(summary(await report(db)))

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
