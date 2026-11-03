"""Replays a news-scoring prompt over old company news whose outcome is known, on the
same items the stored scores cover, and compares them. Read-only: it never writes a
score. A prompt ships to `sentiment:` only if this beats what is stored.

Each item sees only what it could have seen: bars up to publication and the price
stored at scoring time (`news_outcomes.base`). The model may still know what followed
if its training reaches those dates, so treat a win as an upper bound.

    python -m backend.datalayer.prompt_eval --items 200
"""

import argparse
import asyncio
from collections import defaultdict

from backend.datalayer import news, news_sources
from backend.datalayer.accuracy import MIN_DIRECTION, PRICED
from backend.datalayer.outcomes import COLLECTION as OUTCOMES, _sign

MEASURES = ("move_1d", "move_5d", "pre_move_5d", "sector_move_5d")


def _hit(rows: list[dict], direction: str, measure: str) -> tuple[int, float | None]:
    points = [_sign(r[measure]) == _sign(r[direction]) for r in rows
              if r.get(measure) is not None and abs(r.get(direction) or 0) >= MIN_DIRECTION]
    return len(points), sum(points) / len(points) if points else None


def compare(rows: list[dict]) -> list[dict]:
    """rows: outcomes with `direction` (stored) and, once replayed, `new_direction` and `new_priced_in`.
    Only rows the new prompt also scored count, so both columns read the same items."""
    rows = [r for r in rows if r.get("new_direction") is not None]
    fresh = [r for r in rows if r.get("new_priced_in") is not None and r["new_priced_in"] < PRICED]
    priced = [r for r in rows if r.get("new_priced_in") is not None and r["new_priced_in"] >= PRICED]
    groups = [("stored score", rows, "direction"), ("new prompt", rows, "new_direction"),
              ("new, fresh", fresh, "new_direction"), ("new, priced in", priced, "new_direction")]
    return [{"group": name, "measure": m, "n": n, "hit": hit}
            for name, part, field in groups for m in MEASURES for n, hit in [_hit(part, field, m)]]


async def _replay(db, rows: list[dict], names, sector_of, sectors) -> None:
    by_item = defaultdict(list)
    for row in rows:
        by_item[row["item_id"]].append(row)
    docs = await db["news_items"].find({"_id": {"$in": list(by_item)}}).to_list(length=None)

    def ltp_of(doc, symbol):
        return next(((r.get("base") or {}).get(symbol) for r in by_item[doc["_id"]] if r["target"] == symbol), None)

    async def one(batch):
        notes = await news.price_notes(db, batch, ltp_of)
        result = await news._ask("score_market_news", news._deep, news._Scores, sectors=", ".join(sectors),
                                 items=news.score_lines(batch, names, sector_of, notes))
        if result is news._OUTAGE or result is None:
            return
        for scored in result.items:
            if not 0 <= scored.index < len(batch):
                continue
            impacts = news.valid_impacts(scored.impacts, set(names), set(sectors))
            for impact in impacts:
                for row in by_item[batch[scored.index]["_id"]]:
                    if impact["type"] == row["type"] and impact["target"] == row["target"]:
                        row["new_direction"], row["new_priced_in"] = impact["direction"], impact.get("priced_in")

    batches = [docs[i:i + news.SCORE_BATCH] for i in range(0, len(docs), news.SCORE_BATCH)]
    await asyncio.gather(*(one(b) for b in batches))


async def main(items: int) -> None:
    from backend.database import db

    await db.connect_to_database()
    names, sector_of = await news.followed(db.db)
    query = {"scope": "COMPANY", "type": "symbol", "move_5d": {"$ne": None}, "base": {"$ne": None}}
    rows = await db.db[OUTCOMES].find(query).sort("published_at", -1).limit(items).to_list(length=None)
    await _replay(db.db, rows, names, sector_of, news_sources.sectors())
    print(f"{len(rows)} outcome rows, {sum(r.get('new_direction') is not None for r in rows)} scored by the new prompt")
    for cell in compare(rows):
        print(f"{cell['group']:<16}{cell['measure']:<16}n {cell['n']:>4}  hit "
              + ("  -" if cell["hit"] is None else f"{cell['hit']:.0%}"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=200)
    asyncio.run(main(parser.parse_args().items))
