"""The autopilot's one entry source: a weekly relative-strength rotation on
the AI account (spec docs/superpowers/specs/2026-11-02-rotation-autopilot-design.md).

- Once a week (the first morning pass of an ISO week) the target is decided
  from the last session's closes with `factor.model.target_book(ROTATION)`:
  top 8 Nifty 200 names by 3/6-month risk-adjusted strength + nearness to the
  52-week high, equal weight, a holding kept while it ranks within 25; all
  cash when the Nifty is under its 200-DMA. Stored in `rotation_targets`, so
  every worker trades the same book. No per-name stop and no breadth filter:
  both cut net returns in every walk-forward variant (2026-11-02, spec).
- News only ever removes: no buy of a name with stock sentiment <= NEWS_VETO or
  results within RESULTS_DAYS; a held name with bad news is flagged in the plan.
- Every 15-minute pass trades the book toward the target through
  `service.submit` (fence, kill switch, paper/live switch): sells first, then
  buys sized to weight x book value. A refused buy retries at the next pass.

The book's capital is the user's `max_exposure`; each name is also held under
`per_trade_cap` by the fence. The daily plan (`plan`) is pure arithmetic:
the LLM never decides what is bought."""

import asyncio
import logging
from datetime import date, datetime, timedelta

import pandas as pd

from backend.autopilot import service
from backend.core.models import Side
from backend.engine.persistence import trade_net
from backend.engine.session import IST
from backend.factor import data, model
from backend.factor.model import ROTATION
from backend.marks import ORDER_MAX_AGE_SECONDS, mark_prices
from backend.prefs import PrefsStore

logger = logging.getLogger(__name__)
SOURCE = STRATEGY = "rotation"
TARGETS = "rotation_targets"
PLANS = "rotation_plans"
# ponytail: fixed news thresholds, untested on history (no sentiment archive before 2026-10);
# re-tune once rotation_plans holds a few months of vetoes and their outcomes.
NEWS_VETO = -0.5
RESULTS_DAYS = 3


def week_of(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _load() -> tuple[pd.DataFrame, pd.Series]:
    return data.closes(data.universe()), data.series(data.MARKET)


def _settled(closes: pd.DataFrame, today: date) -> pd.DataFrame:
    """Closes of finished sessions only: during the session yfinance's last row is today's live price."""
    return closes.loc[:pd.Timestamp(today) - pd.Timedelta(days=1)]


async def news_flags(db, redis, symbols: set, today: date) -> dict[str, str]:
    """symbol -> why news rules it out of a buy (bad sentiment, results due)."""
    from backend.mine.events import upcoming
    import json

    flags = {}
    if not symbols:
        return flags
    ordered = sorted(symbols)
    raws = await redis.mget([f"sentiment:{s}" for s in ordered]) if redis is not None else [None] * len(ordered)
    for symbol, raw in zip(ordered, raws):
        try:
            value = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            value = None
        score = value.get("score") if isinstance(value, dict) else value
        if isinstance(score, (int, float)) and score <= NEWS_VETO:
            flags[symbol] = f"news sentiment {score:+.2f}"
    for e in await upcoming(db, ordered, today, RESULTS_DAYS):
        if e.get("kind") == "results":
            flags.setdefault(e["symbol"], f"results on {e['date']}")
    return flags


async def rotation_trades(db, user_id: str) -> list[dict]:
    return [t for t in await service.open_trades(db, user_id) if t.get("strategy") == STRATEGY and t["side"] == "BUY"]


async def book_value(db, user_id: str, capital: float, marks: dict) -> float:
    """Capital plus every closed rotation trade's net P&L plus open marks."""
    closed = await db["paper_trades"].find({**service.trades_query(user_id), "strategy": STRATEGY,
                                            "status": "CLOSED"}).to_list(length=None)
    held = await rotation_trades(db, user_id)
    unreal = sum((marks.get(t["symbol"], t["entry_price"]) - t["entry_price"]) * t["quantity"] for t in held)
    return capital + sum(trade_net(t) for t in closed) + unreal


async def target(db, redis, user_id: str, now: datetime, load=None) -> dict:
    """This week's target, decided once from the last session's closes."""
    today = now.astimezone(IST).date()
    key = f"{user_id}:{week_of(today)}"
    doc = await db[TARGETS].find_one({"_id": key})
    if doc:
        return doc
    closes, market = await asyncio.to_thread(load or _load)
    closes, market = _settled(closes, today), market.loc[:pd.Timestamp(today) - pd.Timedelta(days=1)]
    t = closes.index[-1]
    prefs = await PrefsStore(db).get(user_id)
    held = {tr["symbol"] for tr in await rotation_trades(db, user_id)}
    from backend.profile.store import ProfileStore
    avoid = set((await ProfileStore(db).get(user_id)).get("avoid") or [])
    slot = min(float(prefs["max_exposure"]) / ROTATION.top_n, float(prefs["per_trade_cap"]))
    last = closes.iloc[-1]
    too_dear = {s for s, p in last.items() if pd.notna(p) and p > slot and s not in held}
    news = await news_flags(db, redis, set(model.scores(closes, t, ROTATION).head(30).index) - held, today)
    weights, level = model.target_book(closes, market, t, held, ROTATION, avoid=avoid | too_dear | set(news))
    ranked = model.scores(closes, t, ROTATION)
    nifty = market.dropna()
    doc = {"_id": key, "user_id": user_id, "week": week_of(today), "decided_on": str(t.date()),
           "weights": {s: round(float(w), 4) for s, w in weights.items()}, "exposure": round(float(level), 3),
           "breadth": round(model.breadth(closes, t), 3),
           "nifty_vs_200dma": round(float(nifty.iloc[-1] / nifty.iloc[-ROTATION.trend_days:].mean() - 1), 4),
           "ranks": [{"symbol": s, "score": round(float(v), 3)} for s, v in ranked.head(15).items()],
           "news_vetoed": news, "made_at": now}
    await db[TARGETS].replace_one({"_id": key}, doc, upsert=True)
    return doc


async def rebalance(db, redis, user_id: str, now: datetime, load=None, buy: bool = True) -> list[dict]:
    """Trades the book toward this week's target: sells first, then buys (`buy`
    False with the autopilot off: exits still run, no refused-buy noise)."""
    doc = await target(db, redis, user_id, now, load)
    weights = doc["weights"]
    trades = await rotation_trades(db, user_id)
    held = {t["symbol"]: t for t in trades}
    results = []
    for s, t in held.items():
        if s in weights:
            continue
        why = "Out of the risk-off filter's book: the Nifty is under its 200-DMA." if not weights \
            else "Dropped out of the top ranks."
        results.append(await service.submit(db, redis, user_id, service.AutopilotOrder(
            symbol=s, side=Side.SELL, quantity=int(t["quantity"]), product="CNC", source=SOURCE,
            reason=why, strategy=STRATEGY, live=t["user_id"] == service.ledger_user(user_id)), now=now, quiet=True))
    buys = [s for s in weights if s not in held] if buy else []
    if not buys:
        return results
    prefs = await PrefsStore(db).get(user_id)
    news = await news_flags(db, redis, set(buys), now.astimezone(IST).date())
    marks = await mark_prices(db, set(buys) | set(held), max_age_seconds=ORDER_MAX_AGE_SECONDS)
    value = min(await book_value(db, user_id, float(prefs["max_exposure"]), marks), float(prefs["max_exposure"]))
    for s in sorted(buys, key=lambda x: -weights[x]):
        price = marks.get(s)
        if s in news or not price:
            continue
        quantity = int(min(weights[s] * value, float(prefs["per_trade_cap"])) // price)
        if quantity < 1:
            continue
        results.append(await service.submit(db, redis, user_id, service.AutopilotOrder(
            symbol=s, side=Side.BUY, quantity=quantity, product="CNC", source=SOURCE, strategy=STRATEGY,
            reason=f"Weekly rotation {doc['week']}: rank {_rank(doc, s)} of the Nifty 200 by relative strength.",
            context={"week": doc["week"], "reason_codes": ["rotation_top_rank"], "weight": weights[s]}),
            now=now, quiet=True))
    return results


def _rank(doc: dict, symbol: str) -> str:
    for i, row in enumerate(doc.get("ranks") or [], 1):
        if row["symbol"] == symbol:
            return str(i)
    return "top"


def next_rebalance(today: date) -> date:
    from backend.core.market_calendar import is_trading_day

    day = today + timedelta(days=7 - today.weekday())  # next Monday
    while not is_trading_day(day):
        day += timedelta(days=1)
    return day


async def plan(db, redis, user_id: str, now: datetime, load=None) -> dict:
    """Today's plan for the AI account: regime, holdings,
    what the book will do today, news flags. Stored in `rotation_plans`."""
    today = now.astimezone(IST).date()
    doc = await target(db, redis, user_id, now, load)
    trades = await rotation_trades(db, user_id)
    held = {t["symbol"]: t for t in trades}
    marks = await mark_prices(db, set(held) | set(doc["weights"]))
    news = await news_flags(db, redis, set(held) | set(doc["weights"]), today)
    holdings = []
    for s, t in held.items():
        mark = marks.get(s) or t["entry_price"]
        rank = _rank(doc, s)
        holdings.append({"symbol": s, "quantity": t["quantity"], "entry": t["entry_price"], "mark": mark,
                         "pnl_pct": round(mark / t["entry_price"] - 1, 4), "rank": None if rank == "top" else int(rank),
                         "news": news.get(s)})
    sells = [{"symbol": s, "why": "risk_off" if doc["exposure"] == 0 else "rank"} for s in held
             if s not in doc["weights"]]
    buys = [{"symbol": s, "weight": w, "blocked": news.get(s)} for s, w in doc["weights"].items()
            if s not in held]
    prefs = await PrefsStore(db).get(user_id)
    out = {"_id": f"{user_id}:{today.isoformat()}", "user_id": user_id, "date": today.isoformat(),
           "week": doc["week"], "decided_on": doc["decided_on"], "exposure": doc["exposure"],
           "risk_off": doc["exposure"] == 0, "breadth": doc["breadth"], "nifty_vs_200dma": doc["nifty_vs_200dma"],
           "holdings": holdings, "sells": sells, "buys": buys, "news_vetoed": doc.get("news_vetoed") or {},
           "watch": doc.get("ranks", [])[:10], "next_rebalance": next_rebalance(today).isoformat(),
           "live": bool(prefs.get("autopilot_live")), "enabled": bool(prefs.get("autopilot_enabled")),
           "made_at": now}
    await db[PLANS].replace_one({"_id": out["_id"]}, out, upsert=True)
    return out


def plan_text(p: dict) -> list[str]:
    """Telegram lines for the daily plan."""
    lines = []
    if p["risk_off"]:
        lines.append(f"Risk-off: Nifty {p['nifty_vs_200dma']:+.1%} vs its 200-DMA, breadth {p['breadth']:.0%}. "
                     "Book stays in cash.")
    else:
        lines.append(f"Risk-on: Nifty {p['nifty_vs_200dma']:+.1%} vs its 200-DMA, breadth {p['breadth']:.0%}.")
    for h in p["holdings"]:
        flag = f" ⚠ {h['news']}" if h.get("news") else ""
        rank = f", rank {h['rank']}" if h.get("rank") else ""
        lines.append(f"Hold {h['symbol']} {h['pnl_pct']:+.1%}{rank}{flag}")
    for s in p["sells"]:
        lines.append(f"Sell {s['symbol']}: {'risk-off, to cash' if s['why'] == 'risk_off' else 'out of the top ranks'}")
    for b in p["buys"]:
        lines.append(f"Buy {b['symbol']} ({b['weight']:.0%})" + (f": blocked, {b['blocked']}" if b.get("blocked") else ""))
    for s, why in (p.get("news_vetoed") or {}).items():
        lines.append(f"Skipped {s} this week: {why}")
    lines.append(f"Next rebalance {p['next_rebalance']}. {'Live' if p['live'] else 'Paper'}"
                 f"{'' if p['enabled'] else ', autopilot off: no new buys'}.")
    return lines
