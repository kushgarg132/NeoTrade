""""Needs you": the ranked list of what the user should do about their own
account, one function for /mine/actions, Today and both Telegram digests.
Each action's id pins the instance (`kind:symbol:key`), so a dismissed item
stays dismissed until something new happens. Nothing here places an order."""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from backend.engine.session import IST

RANK = {"stop_hit": 10, "idea_exit": 15, "target_hit": 20, "verdict_worse": 30, "bad_news": 40, "idea": 45,
        "review_due": 50, "results_soon": 60, "overweight": 70, "ltcg_soon": 80, "harvest": 85,
        "ex_dividend": 90, "add": 95}
VERDICT_KINDS = {"verdict_worse", "add"}
STATE = "mine_action_state"
EVENT_DAYS = 7
LTCG_DAYS = 30
SNOOZE_DAYS = 7
ALERT_TTL = 30 * 86_400  # seconds a stop/target alert is not repeated
PENDING_IDEAS = {"status": "PENDING", "mode": "LONGTERM"}  # what Decisions lists


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


def _action(kind: str, symbol: str, key, title: str, detail: str, at: datetime, action: dict) -> dict:
    return {"id": f"{kind}:{symbol}:{key}", "kind": kind, "symbol": symbol, "title": title, "detail": detail,
            "rank": RANK[kind], "at": at, "action": action}


async def ideas(db, user_id: str) -> list[dict]:
    """Pending ideas for the user's own account: proven strategies only."""
    from backend.risk.paper_gate import for_mine
    from backend.suggestions.notify import is_admin

    if not await is_admin(db, user_id):  # engine ideas are admin-only (audit W1)
        return []
    return await for_mine(db, user_id, await db["suggestions"].find(
        PENDING_IDEAS | {"user_id": user_id}).to_list(length=200))


def _levels(held: dict[str, float], theses: dict[str, dict], marks: dict[str, float], now: datetime) -> list[dict]:
    out = []
    for symbol, qty in held.items():
        t, price = theses.get(symbol) or {}, marks.get(symbol)
        if price is None:
            continue
        ticket = {"type": "ticket", "side": "SELL", "quantity": qty, "price": price}
        if t.get("stop") and price <= t["stop"]:
            out.append(_action("stop_hit", symbol, f"{t['stop']:g}", f"{symbol} hit your stop ₹{t['stop']:,.2f}",
                               f"Last ₹{price:,.2f}. Your own stop: you place the sell.", now, ticket))
        elif t.get("target") and price >= t["target"]:
            out.append(_action("target_hit", symbol, f"{t['target']:g}",
                               f"{symbol} reached your target ₹{t['target']:,.2f}",
                               f"Last ₹{price:,.2f}. Sell, or raise the target in your thesis.", now, ticket))
    return out


async def _marks(db, symbols) -> dict[str, float]:
    from backend.suggestions import exits

    return await exits.mark_prices(db, list(symbols)) if symbols else {}


async def _hidden(db, user_id: str, now: datetime) -> set[str]:
    return {d["action_id"] async for d in db[STATE].find({"user_id": user_id})
            if d["state"] == "dismissed" or (_aware(d.get("until")) or now) > now}


async def build(db, user_id: str, now: datetime, show_verdicts: bool) -> list[dict]:
    from backend.mine import events, tax
    from backend.mine.lots import mine_trades
    from backend.mine.thesis import ThesisStore
    from backend.portfolio.digest import NEWS_LOOKBACK, headlines_for
    from backend.portfolio.rebalance import suggest, target_gaps
    from backend.portfolio.rules import worsened
    from backend.portfolio.service import latest_snapshot, mine_avg_prices, mine_holdings
    from backend.engine.persistence import mine_book
    from backend.prefs import PrefsStore

    today = now.astimezone(IST).date()
    day = today.isoformat()
    held = await mine_holdings(db, user_id)
    theses = await ThesisStore(db).all(user_id)
    marks = await _marks(db, held)
    out = _levels(held, theses, marks, now)

    # An exit level the app alerted on for an idea it placed, still open.
    async for t in db["paper_trades"].find({"user_id": mine_book(user_id), "status": "OPEN",
                                            "alerted.0": {"$exists": True}}):
        s = t["symbol"]
        out.append(_action("idea_exit", s, f"{t.get('id') or t['_id']}:{t['alerted'][-1]}",
                           f"Sell {s}? Its {t['alerted'][-1]} was hit",
                           "The idea's own exit rule. You place the sell.", _aware(t.get("entry_at")) or now,
                           {"type": "ticket", "side": "SELL", "quantity": t.get("quantity"), "price": marks.get(s)}))

    snapshot = await latest_snapshot(db, user_id) or {}
    snap_at = _aware(snapshot.get("at")) or now
    rows = snapshot.get("holdings") or []
    for r in rows:
        s = r["symbol"]
        if show_verdicts and worsened(r.get("previous_verdict"), r.get("verdict", "")):
            out.append(_action("verdict_worse", s, f"{r['previous_verdict']}>{r['verdict']}",
                               f"{s}: {r['previous_verdict']} → {r['verdict']}",
                               ", ".join(r.get("reason_codes") or []).replace("_", " "), snap_at,
                               {"type": "ticket", "side": "SELL", "quantity": held[s], "price": marks.get(s)}
                               if r["verdict"] == "SELL" and s in held else {"type": "stock"}))
        if "overweight" in (r.get("reason_codes") or []) and s in held:
            weight = f"{r['weight_pct']:.0f}% of your account. " if r.get("weight_pct") is not None else ""
            out.append(_action("overweight", s, "limit", f"{s} is above your size limit",
                               f"{weight}Plan new money or trim it.", snap_at, {"type": "rebalance"}))
    if show_verdicts and any(r.get("verdict") == "ADD" for r in rows):
        gaps, total, _ = target_gaps(rows, (await PrefsStore(db).get(user_id))["rebalance_targets"])
        for r in rows:
            if r.get("verdict") != "ADD":
                continue
            buy = suggest({**r, "last_price": marks.get(r["symbol"], r.get("last_price"))}, gaps.get(r["symbol"]), total)
            if buy and buy.get("side") == "BUY":
                out.append(_action("add", r["symbol"], r.get("verdict_since") or "ADD",
                                   f"Add {buy['quantity']} {r['symbol']}",
                                   "An ADD verdict, up to your target weight.", snap_at, {"type": "ticket", **buy}))

    for s, n in (await headlines_for(db, list(held), now - NEWS_LOOKBACK)).items():
        if (n.get("direction") or 0) < 0:
            out.append(_action("bad_news", s, n.get("url"), f"{s}: {n.get('title') or 'bad news'}",
                               "Negative news in the last 36 hours.", n.get("published_at") or now,
                               {"type": "stock", "url": n.get("url"), "news_id": n.get("id"),
                                "impacts": n.get("impacts") or []}))

    for i in await ideas(db, user_id):
        conviction = (i.get("score") or {}).get("final")
        out.append(_action("idea", i["symbol"], i["id"], f"{i.get('side', '')} {i.get('quantity') or 0:g} {i['symbol']}",
                           "Proven idea" + (f" · conviction {conviction:.2f}" if conviction is not None else ""),
                           _aware(i.get("created_at")) or now, {"type": "idea", "suggestion_id": i["id"]}))

    for s, t in theses.items():
        if s in held and t.get("review_by") and t["review_by"] <= day:
            out.append(_action("review_due", s, t["review_by"], f"Review {s}: your review date has come",
                               t.get("why") or "Is your reason for holding it still true?", now, {"type": "stock"}))

    for e in await events.upcoming(db, held, today, EVENT_DAYS):
        if e["kind"] == "results":
            out.append(_action("results_soon", e["symbol"], e["date"], f"{e['symbol']} results on {e['date']}",
                               "Expect a big move either way.", now, {"type": "stock"}))
        elif e["kind"] == "ex_dividend":
            amount = f"₹{e['amount']:g} a share. " if e.get("amount") else ""
            out.append(_action("ex_dividend", e["symbol"], e["date"], f"{e['symbol']} goes ex-dividend on {e['date']}",
                               f"{amount}Hold through it to get the dividend.", now, {"type": "none"}))

    if held:
        fy = tax.current_fy(today)
        report = tax.report(await mine_trades(db, user_id), held, {s: p for s, p in marks.items() if s in held},
                            fy, today, await mine_avg_prices(db, user_id))
        soon: dict[str, dict] = {}
        for lot in report["turning_long"]:
            if lot["days"] <= LTCG_DAYS:
                e = soon.setdefault(lot["symbol"], {"days": lot["days"], "saving": 0.0, "since": lot["buy_date"]})
                e["days"] = min(e["days"], lot["days"])
                e["since"] = min(e["since"], lot["buy_date"])
                e["saving"] += lot["saving"]
        for s, e in soon.items():
            out.append(_action("ltcg_soon", s, e["since"].isoformat(), f"{s} turns long-term in {e['days']} days",
                               f"Selling after that saves about ₹{e['saving']:,.0f} in tax.", now,
                               {"type": "stock", "tab": "lots"}))
        harvest = report["harvest"]
        # Only when selling a loser really takes tax off (loss rows with zero saving are dropped).
        if today.month <= 3 and harvest["loss"]:
            out.append(_action("harvest", "", fy, "Before 31 March: a tax harvest is open",
                               f"{len(harvest['loss'])} loss and {len(harvest['gain'])} gain harvest(s). Estimate, not tax advice.",
                               now, {"type": "tax"}))

    hidden = await _hidden(db, user_id, now)
    out = [a for a in out if a["id"] not in hidden and (show_verdicts or a["kind"] not in VERDICT_KINDS)]
    out.sort(key=lambda a: (a["rank"], -_aware(a["at"]).timestamp()))
    return out


ABOUT = ("title", "symbol", "kind")  # what the row said, kept so the Handled list can show it
HANDLED_LIMIT = 50


async def _set_state(db, user_id: str, action_id: str, state: str, until: Optional[datetime],
                     now: Optional[datetime] = None, about: Optional[dict] = None) -> None:
    kept = {k: str(v)[:200] for k, v in (about or {}).items() if k in ABOUT and v}
    await db[STATE].update_one({"user_id": user_id, "action_id": action_id},
                               {"$set": {"state": state, "until": until, "at": now or datetime.now(timezone.utc), **kept}},
                               upsert=True)


async def dismiss(db, user_id: str, action_id: str, about: Optional[dict] = None, now: Optional[datetime] = None) -> None:
    await _set_state(db, user_id, action_id, "dismissed", None, now, about)


async def snooze(db, user_id: str, action_id: str, now: datetime, days: int = SNOOZE_DAYS,
                 about: Optional[dict] = None) -> None:
    await _set_state(db, user_id, action_id, "snoozed", now + timedelta(days=days), now, about)


async def handled(db, user_id: str, now: datetime) -> list[dict]:
    """The user's rows still hidden by a dismiss or a snooze, newest first. A snooze that ran out is back
    in the list, so it is left out. Rows hidden before `at` was stored sort last."""
    out = []
    async for d in db[STATE].find({"user_id": user_id}, {"_id": 0, "user_id": 0}):
        until = _aware(d.get("until"))
        if d["state"] == "snoozed" and (until is None or until <= now):
            continue
        out.append({**d, "until": until, "at": _aware(d.get("at"))})
    out.sort(key=lambda d: d["at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[:HANDLED_LIMIT]


async def restore(db, user_id: str, action_id: str) -> bool:
    """Undo a dismiss or snooze: the row is back in the list at the next build."""
    return (await db[STATE].delete_one({"user_id": user_id, "action_id": action_id})).deleted_count > 0


async def level_alerts(db, redis, user_id: str, now: datetime) -> list[dict]:
    """Stop / target hits not alerted before: each id once (Redis NX)."""
    from backend.mine.thesis import ThesisStore
    from backend.portfolio.service import mine_holdings

    theses = await ThesisStore(db).all(user_id)
    held = {s: q for s, q in (await mine_holdings(db, user_id)).items()
            if (theses.get(s) or {}).get("stop") or (theses.get(s) or {}).get("target")}
    out = []
    for a in _levels(held, theses, await _marks(db, held), now):
        if await redis.set(f"mine:alert:{user_id}:{a['id']}", "1", nx=True, ex=ALERT_TTL):
            out.append(a)
    return out


def levels_text(alerts: list[dict]) -> str:
    return "\n".join(["Your levels:"] + [f"• {a['title']}. {a['detail']}" for a in alerts])
