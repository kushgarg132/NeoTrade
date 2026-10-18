"""Fetches everything the portfolio review needs and stores the result.

Holdings come from each of the user's connected brokers; buy dates from
their journal; NIFTY history and a year of daily closes from the shared
daily_bars store (yfinance for what it lacks); sectors and each stock's
health from yfinance and the news. Each holding then gets a
rule-scored verdict (rules.py) and the whole an AI write-up (review.py).
Each run is saved to `portfolio_snapshots` (per user_id), so the next can
say what changed. With no broker session (brokers' tokens expire
overnight), the last snapshot's holdings are reused, repriced from
yfinance's latest closes, and the snapshot says so.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

from backend.ai.sentiment import get_cached_sentiment
from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import BROKERS, get_broker_adapter
from backend.datalayer import bars
from backend.core.models import Holding
from backend.journal.store import JournalStore
from backend.marks import mark_prices
from backend.portfolio.health import stock_health
from backend.portfolio.review import write_review
from backend.portfolio.rules import fund_verdict, stock_verdict
from backend.portfolio.scorecard import build_scorecard
from backend.prefs import PrefsStore

logger = logging.getLogger(__name__)

SECTOR_TTL = timedelta(days=30)


def _ticker(symbol: str, exchange: str | None) -> str:
    return f"{symbol}.BO" if exchange == "BSE" else f"{symbol}.NS"


def _nifty_sync() -> list:
    # Ten years: the benchmark needs NIFTY's close on the day of the oldest
    # journal buy still held.
    hist = yf.Ticker("^NSEI").history(period="10y", interval="1d")
    return [(index.date(), float(row["Close"])) for index, row in hist.iterrows()]


async def _nifty() -> list:
    from backend.database import db

    points = await bars.nifty_closes(db.db, bars.today_ist() - timedelta(days=3653))
    if points:
        return points
    try:
        return await asyncio.to_thread(_nifty_sync)
    except Exception as exc:
        logger.warning("portfolio: NIFTY history unavailable: %s", exc)
        return []


def _sector_sync(ticker: str):
    return (yf.Ticker(ticker).info or {}).get("sector")


async def _sectors(db, stocks: list[tuple[str, str | None]]) -> dict:
    """Sector per stock symbol, cached in `instrument_sectors` for a month
    (shared reference data, not per user). None when yfinance has none."""
    cache = db["instrument_sectors"]
    now = datetime.now(timezone.utc)
    known = {
        d["_id"]: d.get("sector")
        for d in await cache.find({"_id": {"$in": [s for s, _ in stocks]}}).to_list(length=None)
        if d["at"].replace(tzinfo=timezone.utc) > now - SECTOR_TTL
    }
    for symbol, exchange in stocks:
        if symbol in known:
            continue
        try:
            known[symbol] = await asyncio.to_thread(_sector_sync, _ticker(symbol, exchange))
        except Exception as exc:
            logger.warning("portfolio: no sector for %s: %s", symbol, exc)
            known[symbol] = None
        await cache.update_one({"_id": symbol}, {"$set": {"sector": known[symbol], "at": now}}, upsert=True)
    return known


def _daily_closes_sync(tickers: dict[str, str]) -> dict:
    """A year of daily closes per symbol, oldest first, as (date, close)."""
    if not tickers:
        return {}
    closes = yf.download(list(tickers.values()), period="1y", interval="1d", progress=False)["Close"]
    if not hasattr(closes, "columns"):  # one ticker comes back as a Series
        closes = closes.to_frame(next(iter(tickers.values())))
    result = {}
    for symbol, ticker in tickers.items():
        if ticker in closes:
            series = closes[ticker].dropna()
            result[symbol] = [(index.date(), float(value)) for index, value in series.items()]
    return result


async def _closes(db, listed: list[tuple[str, str]]) -> dict:
    stored = await bars.read(db, [s for s, e in listed if e != "BSE"], bars.today_ist() - timedelta(days=365))
    closes = {s: [(i.date(), float(c)) for i, c in f["close"].items()] for s, f in stored.items()}
    rest = {s: _ticker(s, e) for s, e in listed if s not in closes}
    try:
        closes |= await asyncio.to_thread(_daily_closes_sync, rest)
    except Exception as exc:
        logger.warning("portfolio: daily closes unavailable: %s", exc)
    return closes


def _returns(closes: list[tuple]) -> dict:
    return {day: close / prev - 1 for (_, prev), (day, close) in zip(closes, closes[1:]) if prev}


async def fetch_holdings(user_id: str, credentials, redis, previous: dict | None = None) -> tuple[list, dict, list]:
    """(holdings read now, the error per broker that failed, holdings carried
    over from `previous` for every broker not read now). A logged-out broker
    must not drop its holdings: with only Kite logged in, the Upstox account
    vanished from the portfolio."""
    holdings, errors, read = [], {}, set()
    for broker in BROKERS:
        adapter = await get_broker_adapter(broker, user_id, credentials, redis)
        if await adapter.state() != BrokerSessionState.ACTIVE:
            continue
        try:
            holdings += await adapter.get_holdings()
            read.add(broker)
        except Exception as exc:
            logger.warning("portfolio: %s holdings failed for %s: %s", broker, user_id, exc)
            errors[broker] = str(exc)
    carried = [Holding(**h) for h in (previous or {}).get("raw_holdings") or [] if h.get("broker") not in read]
    return holdings, errors, carried


async def refresh_portfolio(db, user_id: str, credentials, redis, analyse: bool = True) -> dict:
    previous = await latest_snapshot(db, user_id)
    holdings, errors, carried = await fetch_holdings(user_id, credentials, redis, previous)
    stale_since = (previous.get("stale_since") or previous["at"]) if carried else None

    listed = sorted({(h.symbol, h.exchange) for h in holdings + carried if h.kind != "MF"})
    closes = await _closes(db, listed)
    holdings += [
        h.model_copy(update={"last_price": closes[h.symbol][-1][1], "close_price": closes[h.symbol][-2][1]})
        if len(closes.get(h.symbol, [])) >= 2 else h
        for h in carried
    ]

    stocks = [(s, e) for s, e in listed if next(h for h in holdings if h.symbol == s).kind == "STOCK"]
    returns = {s: _returns(closes[s]) for s, _ in stocks if s in closes}
    trades = await JournalStore(db).list_trades(user_id)
    # The review, its verdicts and its AI text are about the user's own
    # account: the AI account's holdings are the autopilot's business.
    from backend.brokers.roles import brokers_for
    mine = brokers_for((await PrefsStore(db).get(user_id)).get("broker_roles") or {}, "mine")
    if mine:
        trades = [t for t in trades if t.get("broker") in mine]
    reviewed = [h for h in holdings if h.broker in mine] if mine else holdings
    card = build_scorecard(reviewed, trades, await _nifty(), await _sectors(db, stocks), returns)
    if analyse and card["holdings"]:
        await _review(db, user_id, redis, card, closes, previous)

    snapshot = {
        "user_id": user_id, "at": datetime.now(timezone.utc), "errors": errors,
        "brokers": sorted({h.broker for h in holdings}), "stale_since": stale_since,
        "raw_holdings": [h.model_dump() for h in holdings], **card,
    }
    await db["portfolio_snapshots"].insert_one(dict(snapshot))
    # Open holdings pages re-read; outside market hours they don't poll.
    from backend.ws.hub import hub
    await hub.publish(user_id, "portfolio", "refreshed", {"at": snapshot["at"]})
    return snapshot


async def _review(db, user_id: str, redis, card: dict, closes: dict, previous: dict | None) -> None:
    """Adds health, a verdict and the previous run's verdict to every
    holding row, then the AI summary and notes to the card."""
    prefs = await PrefsStore(db).get(user_id)
    limits = {"max_loss_pct": prefs["portfolio_max_loss_pct"], "max_weight_pct": prefs["portfolio_max_weight_pct"]}
    stock_rows = [r for r in card["holdings"] if r["kind"] == "STOCK"]
    health = await stock_health(
        db, stock_rows, {s: [c for _, c in series] for s, series in closes.items()}, datetime.now(timezone.utc),
    )
    before = {r.get("isin") or r["symbol"]: r.get("verdict") for r in (previous or {}).get("holdings", [])}
    since = {r.get("isin") or r["symbol"]: r.get("verdict_since") for r in (previous or {}).get("holdings", [])}
    from backend.engine.session import IST
    today = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
    for row in card["holdings"]:
        if row["kind"] == "STOCK":
            row["health"] = health.get(row["symbol"], {})
            sentiment = await get_cached_sentiment(row["symbol"], redis) if redis is not None else None
            row.update(stock_verdict(row, row["health"], limits, sentiment))
        else:
            row.update(fund_verdict(row, limits))
        key = row.get("isin") or row["symbol"]
        row["previous_verdict"] = before.get(key)
        # The day this verdict began: Needs-you's `add` keys on it, so a dismissal lasts while it holds.
        row["verdict_since"] = since.get(key) if before.get(key) == row.get("verdict") and since.get(key) else today

    try:
        held = {r["symbol"] for r in card["holdings"]}
        review = await write_review(card, await add_candidates(db, user_id, held))
    except Exception as exc:
        logger.warning("portfolio review write-up failed for %s: %s", user_id, exc)
        review = {"summary": None, "notes": {}}
    card["summary"] = review["summary"]
    card["plan"] = review.get("plan")
    for row in card["holdings"]:
        row["note"] = review["notes"].get(row["symbol"])


CANDIDATE_DAYS = 7
MAX_CANDIDATES = 5


async def add_candidates(db, user_id: str, held: set, now: datetime | None = None) -> list[dict]:
    """Stocks the user does not hold that the long-term scan scored as buys
    this past week, best score first, one per symbol: the only stocks the
    action plan may suggest adding. Rejected ones stay out."""
    now = now or datetime.now(timezone.utc)
    docs = await db["suggestions"].find({
        "user_id": user_id, "mode": "LONGTERM", "side": "BUY", "status": {"$ne": "REJECTED"},
        "created_at": {"$gte": now - timedelta(days=CANDIDATE_DAYS)},
    }).to_list(length=None)
    best: dict[str, dict] = {}
    for doc in sorted(docs, key=lambda d: (d.get("score") or {}).get("final") or 0, reverse=True):
        if doc["symbol"] not in held:
            best.setdefault(doc["symbol"], doc)
    return list(best.values())[:MAX_CANDIDATES]


def scorecard_for(snapshot: dict, brokers: set[str], trades: list[dict], nifty: list,
                  verdicts: bool = True) -> dict:
    """One account's view of a snapshot: the scorecard re-run on that
    account's holdings and trades only. The full review's per-holding
    verdicts and sectors carry over by symbol (no new AI call). The AI
    account's view passes `verdicts=False`: the review judges the user's own
    account only, so a symbol both accounts hold must not show it there."""
    from backend.portfolio.scorecard import build_scorecard

    holdings = [Holding(**h) for h in snapshot.get("raw_holdings", []) if h.get("broker") in brokers]
    full = {r["symbol"]: r for r in snapshot.get("holdings", [])}
    sectors = {s: r.get("sector") for s, r in full.items()}
    card = build_scorecard(holdings, [t for t in trades if t.get("broker") in brokers], nifty, sectors, {})
    for row in card["holdings"] if verdicts else []:
        for key in ("verdict", "reason_codes", "health", "score", "note", "previous_verdict"):
            if key in full.get(row["symbol"], {}):
                row[key] = full[row["symbol"]][key]
    return {**snapshot, **card, "brokers": sorted(brokers), "account_view": True}


async def quoted(db, raw: list[dict], now: datetime, read_at: datetime | None = None) -> tuple[list[dict], bool]:
    """Raw holdings repriced from market quotes, no broker call: the last
    price from the quote cache (or yfinance), the day's base from stored
    daily closes. Funds keep their last price. Rows read on an earlier day
    (`read_at`) never keep their own close as the base: with no stored
    close the day move is unknown, not measured from days ago. Second
    value: any quote came."""
    stocks = [h["symbol"] for h in raw if h.get("kind", "STOCK") != "MF"]
    marks = await mark_prices(db, stocks)
    if not marks:
        return raw, False
    today = bars.today_ist(now)
    prev = await bars.prev_closes(db, stocks, today)
    old = read_at is not None and bars.today_ist(read_at) < today
    # No quote: the row keeps its own price, so it keeps its own close only if
    # that read is from today -- an old price against a fresh close is no day move.
    return [{**h, "last_price": marks.get(h["symbol"], h.get("last_price")),
             "close_price": (prev.get(h["symbol"], None if old else h.get("close_price")) if h["symbol"] in marks
                             else None if old else h.get("close_price"))} for h in raw], True


async def with_live_prices(db, user_id: str, snapshot: dict, credentials, redis) -> dict:
    """The snapshot repriced from the brokers right now, for the page's poll.
    Verdicts, notes and the AI review carry over (no AI call); nothing is
    stored. Any broker down or logged out: the last holdings repriced from
    market quotes (stocks only), with `holdings_as_of` saying how old the
    list of holdings is -- never a days-old value shown as today's."""
    holdings, _, carried = await fetch_holdings(user_id, credentials, redis, snapshot)
    now = datetime.now(timezone.utc)
    raw = [h.model_dump() for h in carried]
    if raw:
        raw, priced = await quoted(db, raw, now, snapshot.get("at"))
        if not priced and not holdings:
            return snapshot
    elif not holdings:
        return snapshot
    fresh = {**snapshot, "raw_holdings": [h.model_dump() for h in holdings] + raw, "at": now,
             "stale_since": None, "holdings_as_of": (snapshot.get("stale_since") or snapshot.get("at")) if raw else None}
    brokers = {h["broker"] for h in fresh["raw_holdings"]}
    card = scorecard_for(fresh, brokers, await JournalStore(db).list_trades(user_id), await _nifty())
    # Correlation needs daily returns the poll does not fetch: keep the analysed one.
    card["concentration"]["correlated"] = (snapshot.get("concentration") or {}).get("correlated", [])
    card.pop("account_view", None)
    return card


async def _mine_raw(db, user_id: str) -> list[dict]:
    from backend.brokers.roles import brokers_for

    snapshot = await latest_snapshot(db, user_id) or {}
    mine = brokers_for((await PrefsStore(db).get(user_id)).get("broker_roles") or {}, "mine")
    return [h for h in snapshot.get("raw_holdings") or []
            if h.get("kind", "STOCK") != "MF" and (not mine or h.get("broker") in mine)]


async def mine_holdings(db, user_id: str) -> dict[str, float]:
    """symbol -> quantity the user really holds on their own (`mine`)
    account, from the latest snapshot. With no account roles set, every
    holding is theirs."""
    held: dict[str, float] = {}
    for h in await _mine_raw(db, user_id):
        held[h["symbol"]] = held.get(h["symbol"], 0.0) + h["quantity"]
    return held


async def mine_avg_prices(db, user_id: str) -> dict[str, float]:
    """symbol -> the broker's average buy price on the user's own account."""
    qty: dict[str, float] = {}
    cost: dict[str, float] = {}
    for h in await _mine_raw(db, user_id):
        qty[h["symbol"]] = qty.get(h["symbol"], 0.0) + h["quantity"]
        cost[h["symbol"]] = cost.get(h["symbol"], 0.0) + h["quantity"] * h["avg_price"]
    return {s: cost[s] / q for s, q in qty.items() if q}


async def latest_snapshot(db, user_id: str) -> dict | None:
    docs = await db["portfolio_snapshots"].find({"user_id": user_id}).sort("at", -1).limit(1).to_list(length=1)
    if not docs:
        return None
    docs[0].pop("_id", None)
    return docs[0]


async def daily_reviews(db, redis) -> int:
    """Re-reviews the portfolio of every user with a broker account set or a
    portfolio analysed before, and alerts its owner (socket + Telegram)
    about holdings whose verdict got worse. Run from the daily post-close
    pass (backend/scheduler.py), when the day's broker sessions are valid."""
    from backend.app_settings import AppSettingsStore
    from backend.auth.broker_credentials import BrokerCredentialStore, fernet_from_settings
    from backend.guardrails import telegram
    from backend.portfolio.rules import worsened
    from backend.ws.hub import hub

    credentials = BrokerCredentialStore(db, fernet_from_settings())
    audience = await AppSettingsStore(db).get_portfolio_verdicts()
    reviewed = 0
    users = set(await db["portfolio_snapshots"].distinct("user_id")) | set(
        await db["user_prefs"].distinct("user_id", {"broker_roles": {"$exists": True, "$ne": {}}}))
    for user_id in sorted(users):
        try:
            snapshot = await refresh_portfolio(db, user_id, credentials, redis)
        except Exception as exc:
            logger.exception("daily portfolio review failed for %s: %s", user_id, exc)
            continue
        reviewed += 1
        worse = [r for r in snapshot["holdings"] if worsened(r.get("previous_verdict"), r.get("verdict", ""))]
        if not worse:
            continue
        user = await db["users"].find_one({"id": user_id}) or {}
        show = user.get("role") == "admin" or audience == "all"
        lines = []
        for r in worse:
            label = f"{r['verdict']} (was {r['previous_verdict']})" if show else "worth a closer look"
            reasons = ", ".join(r["reason_codes"]).replace("_", " ")
            lines.append(f"{r['symbol']}: {label} -- {reasons}")
        text = "NeoTrade daily portfolio review\n" + "\n".join(lines)
        await hub.publish(user_id, "portfolio", "worsened", {"symbols": [r["symbol"] for r in worse]})
        await telegram.alert(db, user_id, text)
    return reviewed
