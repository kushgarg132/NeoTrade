"""One stock on the Mine page: the position, its tax lots, the user's thesis,
the verdict over time, upcoming events and news. The user's own account only."""

from datetime import date, datetime, timedelta, timezone

from backend.datalayer import bars
from backend.engine.session import IST
from backend.mine import events, history
from backend.mine.lots import mine_trades, open_lots, realised, reconcile, split_ratio
from backend.mine.tax import LTCG_RATE, STCG_RATE, days_to_long, is_long
from backend.mine.thesis import ThesisStore

NEWS = 10
EVENT_DAYS = 90


async def _verdicts(db, user_id: str, symbol: str, show: bool) -> tuple[dict, list[dict]]:
    """(newest row for the symbol, one entry per change of verdict, oldest first)."""
    from backend.routers.portfolio import mask_row

    row, hist = {}, []
    async for snap in db["portfolio_snapshots"].find({"user_id": user_id}, {"holdings": 1, "at": 1}).sort("at", 1):
        found = next((h for h in snap.get("holdings") or [] if h["symbol"] == symbol), None)
        if not found:
            continue
        row = found if show else mask_row(found)
        if row.get("verdict") and (not hist or hist[-1]["verdict"] != row["verdict"]):
            at = snap["at"] if snap["at"].tzinfo else snap["at"].replace(tzinfo=timezone.utc)
            hist.append({"date": at.astimezone(IST).date().isoformat(), "verdict": row["verdict"]})
    return row, hist


async def _news(db, symbol: str) -> list[dict]:
    from backend.datalayer.news import ref

    out = []
    async for n in db["news_items"].find({"impacts.target": symbol}).sort("published_at", -1).limit(NEWS):
        i = next(i for i in n["impacts"] if i.get("target") == symbol)
        out.append({"title": n.get("event") or n.get("title"), "url": n.get("url"),
                    "published_at": n.get("published_at"), "direction": i.get("direction"), "impact": i.get("impact"),
                    **ref(n)})
    return out


async def detail(db, user_id: str, symbol: str, now: datetime, show_verdicts: bool) -> dict | None:
    """None when the symbol is neither held nor in the journal."""
    from backend.brokers.roles import brokers_for
    from backend.portfolio import service
    from backend.prefs import PrefsStore

    today = now.astimezone(IST).date()
    trades = [t for t in await mine_trades(db, user_id) if t["symbol"] == symbol]
    prefs = await PrefsStore(db).get(user_id)
    mine = brokers_for(prefs.get("broker_roles") or {}, "mine")
    snap = await service.latest_snapshot(db, user_id) or {}
    raw = [h for h in snap.get("raw_holdings") or []
           if h["symbol"] == symbol and h.get("kind", "STOCK") != "MF" and (not mine or h.get("broker") in mine)]
    if not raw and not trades:
        return None
    raw, _ = await service.quoted(db, raw, now, snap.get("at"))
    qty = sum(h["quantity"] for h in raw)

    frame = (await bars.read(db, [symbol], today - timedelta(days=365), today)).get(symbol)
    closes = [] if frame is None else [{"date": d.date().isoformat(), "close": float(c)} for d, c in frame["close"].items()]
    last = next((h["last_price"] for h in raw if h.get("last_price")), None) or (closes[-1]["close"] if closes else None)

    cost = sum(h["quantity"] * h["avg_price"] for h in raw)
    broker_avg = cost / qty if qty else None
    journal_lots = open_lots(trades, symbol)
    lots, unknown = reconcile(journal_lots, qty, broker_avg)
    ratio = split_ratio(journal_lots, qty, broker_avg)  # bars are split-adjusted; the journal is not
    lot_rows = []
    for d, q, p in lots:
        gain = None if last is None else (last - p) * q
        rate = LTCG_RATE if is_long(d, today) else STCG_RATE
        lot_rows.append({"buy_date": d.isoformat(), "qty": q, "price": p, "gain": gain,
                         "days_to_long": days_to_long(d, today),
                         "est_tax": None if gain is None else max(gain, 0) * rate})

    value = None if last is None else qty * last
    # Held but unpriced: unknown, not the realised sum (a different thing).
    pnl = (value - cost if value is not None else None) if qty else sum(r["gain"] for r in realised(trades, symbol))
    divs = await events.dividends_received(db, trades, symbol, today, ratio)
    flows = [(t["traded_at"].astimezone(IST).date(),
              (-1 if t["side"] == "BUY" else 1) * float(t["quantity"]) * float(t["price"])) for t in trades]
    flows += [(date.fromisoformat(x["date"]), x["amount"]) for x in divs]
    # Only shares with a known buy flow count at the end: unknown ones have no money in.
    if value and qty - unknown > 1e-9:
        flows.append((today, (qty - unknown) * last))
    first = min((d for d, _, _ in lots), default=None) or min((f[0] for f in flows), default=None)

    row, hist = await _verdicts(db, user_id, symbol, show_verdicts)
    return {
        "position": {"qty": qty, "avg_price": cost / qty if qty else None, "value": value, "pnl": pnl,
                     "pnl_pct": pnl / cost * 100 if qty and cost and pnl is not None else None,
                     "xirr": None if unknown > 1e-9 and not lots else history.xirr(flows),
                     "held_since": first.isoformat() if first else None, "sold": qty <= 0},
        "lots": lot_rows, "unknown_qty": unknown,
        "thesis": await ThesisStore(db).get(user_id, symbol) or {},
        "verdict": {"current": row.get("verdict"), "reasons": row.get("reason_codes") or [],
                    "note": row.get("note"), "history": hist, "since": row.get("verdict_since"),
                    # The figures the rules read (portfolio/rules.py) and the limits they compare against.
                    "facts": {**{k: row.get(k) for k in ("pnl_pct", "weight_pct", "nifty_pnl_pct", "first_bought")},
                              **((row.get("health") or {}).get("trend") or {}),
                              **((row.get("health") or {}).get("fundamentals") or {})} if row else {},
                    "limits": {"max_loss_pct": prefs.get("portfolio_max_loss_pct"),
                               "max_weight_pct": prefs.get("portfolio_max_weight_pct")}},
        "events": await events.upcoming(db, [symbol], today, EVENT_DAYS),
        "past_events": await events.past(db, symbol, today),
        "dividends": divs,
        "news": await _news(db, symbol),
        "closes": closes,
        "trades": [{"date": t["traded_at"].astimezone(IST).date().isoformat(), "side": t["side"],
                    "qty": float(t["quantity"]) * ratio, "price": float(t["price"]) / ratio}
                   for t in sorted(trades, key=lambda t: t["traded_at"])],
    }
