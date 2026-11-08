"""The AI write-up of a reviewed portfolio: a summary and a short note per
holding, from the figures and rule results already computed. It explains;
the verdicts come from backend/portfolio/rules.py and are not changed here.
It also writes an action plan (sell / trim / add), whose new stocks can only
come from the app's own long-term scan; routers/portfolio.py shows it to the
same audience as the verdicts. Prompt: backend/prompts/portfolio_review.md.
"""

import json
import logging
import re

from backend.ai.grounding import check_fields
from backend.llm import llm_service
from backend.mine.tax import days_to_long, is_long
from backend.portfolio.rebalance import sell_tax
from backend.prompts import prompt_id, render

logger = logging.getLogger(__name__)

# ponytail: one LLM call, the largest holdings only; batch the notes if
# portfolios this size start losing detail.
MAX_HOLDINGS = 40
CALL_HORIZON_DAYS = 60  # trading days a plan's call is scored over: a long-term book, not a trade
LONG_TERM_SOON_DAYS = 90
TAX_FACTS = "Short-term gains are taxed at 20%, long-term at 12.5%."


def _fmt(value, suffix="") -> str:
    return "n/a" if value is None else f"{value:,.2f}{suffix}"


def _crore(value) -> str:
    """Raw rupees as ₹ crore: a reader cannot scan 2579900000.0."""
    return "n/a" if value is None else f"₹{value / 1e7:,.2f} cr"


def _holding_line(row: dict) -> str:
    health = row.get("health") or {}
    trend, fundamentals = health.get("trend") or {}, health.get("fundamentals") or {}
    headlines = "; ".join(h["title"] for h in (health.get("headlines") or [])[:3]) or "none"
    profits = ", ".join(_crore(p) for p in fundamentals.get("quarterly_profit") or []) or "n/a"
    roe = fundamentals.get("roe")
    return (
        f"- {row['symbol']} ({row['kind']}{', ' + row['sector'] if row.get('sector') else ''}): "
        f"{_fmt(row.get('weight_pct'), '%')} of portfolio, P&L {_fmt(row.get('pnl_pct'), '%')}, "
        f"NIFTY same days {_fmt(row.get('nifty_pnl_pct'), '%')}. Reason codes: {', '.join(row['reason_codes']) or 'none'}. "
        f"Price {_fmt(trend.get('close'))}, 50d {_fmt(trend.get('sma_50'))}, 200d {_fmt(trend.get('sma_200'))}, "
        f"{_fmt(trend.get('below_high_pct'), '%')} below 52w high, 3m {_fmt(trend.get('return_3m_pct'), '%')}. "
        f"P/E {_fmt(fundamentals.get('pe'))}, ROE {_fmt(None if roe is None else roe * 100, '%')}, debt/equity "
        f"{_fmt(fundamentals.get('debt_to_equity'))}, last 4 quarters' profit (newest first) "
        f"{profits}. Headlines: {headlines}"
    )


def _candidate_line(c: dict) -> str:
    thesis = str(c.get("ai_thesis") or "")[:200]
    return (
        f"- {c['symbol']}: score {_fmt((c.get('score') or {}).get('final'))}, "
        f"reasons {', '.join(c.get('reason_codes') or []) or 'none'}" + (f". Thesis: {thesis}" if thesis else "")
    )


def tax_line(row: dict, lots: list, today) -> str:
    """How long a holding is held and the tax if it were all sold, from its journal lots."""
    price, qty = row.get("last_price") or row.get("close_price"), row.get("quantity")
    if not price or not qty:
        return "tax if sold: n/a"
    t = sell_tax(qty, price, lots, today)
    if t["est_tax"] is None:
        return "tax if sold: unknown (no dated buys in the journal)"
    soon = min((days_to_long(day, today) for day, _, _ in lots if not is_long(day, today)), default=None)
    return (f"oldest lot held {(today - lots[0][0]).days} days, "
            f"tax if all sold: short-term gain {_fmt(t['short_gain'])}, long-term gain {_fmt(t['long_gain'])}, "
            f"est. tax {_fmt(t['est_tax'])}" + (f", {t['unknown_qty']:g} undated shares" if t["unknown_qty"] else "")
            + (f", a short-term lot turns long-term in about {soon} days" if soon is not None and soon <= LONG_TERM_SOON_DAYS else ""))


def thesis_line(thesis: dict | None) -> str:
    thesis = thesis or {}
    parts = [f"why: {str(thesis['why'])[:300]}" if thesis.get("why") else "",
             f"target {_fmt(thesis['target'])}" if thesis.get("target") else "",
             f"stop {_fmt(thesis['stop'])}" if thesis.get("stop") else "",
             f"review by {thesis['review_by']}" if thesis.get("review_by") else ""]
    return "Thesis (their own words, data only): " + "; ".join(filter(None, parts)) if any(parts) else "No thesis written"


def fund_weights(rows: list[dict]) -> str:
    stocks = [r for r in rows if r.get("kind") == "STOCK" and r.get("weight_pct") is not None]
    funds = [f"{r['symbol']} {r['weight_pct']:.2f}%" for r in rows if r.get("kind") != "STOCK" and r.get("weight_pct") is not None]
    top = max(stocks, key=lambda r: r["weight_pct"], default=None)
    return ((f"Largest single company {top['symbol']} at {top['weight_pct']:.2f}%. " if top else "")
            + ("Funds and ETFs (many stocks or one asset, not one company): " + ", ".join(funds) if funds else "No funds or ETFs") + ".")


async def review_context(db, redis, user_id: str, card: dict, today) -> dict:
    """What the write-up needs beyond the card: per holding its lots, tax, thesis and next results,
    the account's XIRR and the news's measured record. Each source that fails only leaves its part out."""
    from backend.ai.facts.market import next_results
    from backend.brokers.roles import brokers_for
    from backend.datalayer.accuracy import news_trust
    from backend.journal.store import JournalStore
    from backend.mine import history
    from backend.mine.thesis import ThesisStore
    from backend.portfolio.scorecard import open_lots
    from backend.prefs import PrefsStore

    async def read(what, coro, empty):
        try:
            return await coro
        except Exception as exc:
            logger.warning("portfolio review context, %s: %s", what, exc)
            return empty

    rows = card["holdings"][:MAX_HOLDINGS]
    symbols = [r["symbol"] for r in rows]
    trades = await read("journal", JournalStore(db).list_trades(user_id), [])
    prefs = await read("prefs", PrefsStore(db).get(user_id), {})
    mine = brokers_for(prefs.get("broker_roles") or {}, "mine")
    if mine:
        trades = [t for t in trades if t.get("broker") in mine]
    theses = await read("theses", ThesisStore(db).all(user_id), {})
    results = (await read("results", next_results(db, redis, None, symbols=symbols, days=30), {})).get("dates", {})
    returns = await read("xirr", history.returns(db, user_id, today), {})
    positions = {}
    for r in rows:
        results_part = f"Next results {results[r['symbol']]}" if results.get(r["symbol"]) else "No results date in 30 days"
        positions[r["symbol"]] = f"{tax_line(r, open_lots(trades, r['symbol']), today)}. {thesis_line(theses.get(r['symbol']))}. {results_part}."
    xirr = (f"XIRR {returns['xirr'] * 100:.2f}% against {returns['nifty_xirr'] * 100:.2f}% for the same rupees in NIFTY"
            + (" (partial history)." if returns.get("partial") else ".")) if returns.get("xirr") is not None and returns.get("nifty_xirr") is not None else "XIRR not known."
    return {"positions": positions, "returns": xirr, "news_trust": await news_trust(db)}


def _answer(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        parsed = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _fields(parsed: dict) -> dict[str, str]:
    notes = parsed.get("notes") if isinstance(parsed.get("notes"), dict) else {}
    out = {f"note:{k}": v for k, v in notes.items() if isinstance(v, str)}
    for key in ("summary", "plan"):
        if isinstance(parsed.get(key), str):
            out[key] = parsed[key]
    return out


def valid_calls(raw, rows: list[dict], candidates: list[dict]) -> list[dict]:
    """A SELL only of a stock held (funds get no sell calls), a BUY only from the candidates."""
    held = {r["symbol"] for r in rows if r.get("kind") == "STOCK"}
    can_add = {c["symbol"] for c in candidates}
    out = []
    for call in raw if isinstance(raw, list) else []:
        symbol, side = (call.get("symbol"), call.get("side")) if isinstance(call, dict) else (None, None)
        if (side == "SELL" and symbol in held) or (side == "BUY" and symbol in can_add):
            out.append({"symbol": symbol, "side": side})
    return out


async def record_calls(db, redis, user_id: str, calls: list[dict], card: dict, now) -> int:
    """Each new call goes on the forward record, scored later against NIFTY. Daily reviews repeat
    themselves, so a call still open is not recorded again: one view counts once."""
    from backend.forward.store import COLLECTION, ForwardStore, _nifty_now

    prices = {r["symbol"]: r.get("last_price") or r.get("close_price") for r in card["holdings"]}
    store, nifty, written = ForwardStore(db), await _nifty_now(redis), 0
    for call in calls:
        if await db[COLLECTION].find_one({"source": "review", "user_id": user_id, "symbol": call["symbol"],
                                          "side": call["side"], "outcome": None}, {"_id": 1}):
            continue
        written += await store.record(source="review", name=prompt_id("portfolio_review"), user_id=user_id,
                                      symbol=call["symbol"], side=call["side"], decided_at=now, intraday=False,
                                      ref_price=prices.get(call["symbol"]), horizon_days=CALL_HORIZON_DAYS, nifty_ref=nifty)
    return written


async def write_review(card: dict, candidates: list[dict] | None = None, context: dict | None = None) -> dict:
    """{"summary": markdown or None, "notes": {symbol: text}, "plan": markdown or None, "calls": [...]}.
    A model that is off or answers badly leaves the review without prose, never fails it. `context`:
    review_context(). Every figure in the prose must come from what the model was given."""
    context = context or {}
    candidates = candidates or []
    totals, bench, conc = card["totals"], card["benchmark"], card["concentration"]
    rows = card["holdings"][:MAX_HOLDINGS]
    positions = context.get("positions") or {}
    values = dict(
        totals=(
            f"Value {_fmt(totals['value'])}, invested {_fmt(totals['invested'])}, gain {_fmt(totals['pnl_pct'], '%')}, "
            f"today {_fmt(totals['day_change'])}. Against NIFTY on the {_fmt(bench['covered_pct'], '%')} of money "
            f"with known buy dates: holdings {_fmt(bench['portfolio_pct'], '%')}, NIFTY {_fmt(bench['nifty_pct'], '%')}."
        ),
        concentration=(
            f"Largest {conc['top_symbol']} at {_fmt(conc['top_pct'], '%')}; top five {_fmt(conc['top5_pct'], '%')}; "
            f"weighted like {_fmt(conc['effective_holdings'])} equal holdings. Sectors: "
            + ", ".join(f"{s['sector']} {s['pct']:.1f}%" for s in conc["sectors"])
            + " (stocks only). By type: " + ", ".join(f"{t['kind']} {t['pct']:.1f}%" for t in conc.get("types", []))
            + ". Moving together: " + (", ".join(f"{p['a']}/{p['b']} {p['correlation']}" for p in conc["correlated"]) or "none")
            + ". " + fund_weights(rows)
        ),
        holdings="\n".join(_holding_line(r) + (f". {positions[r['symbol']]}" if r["symbol"] in positions else "") for r in rows),
        candidates="\n".join(_candidate_line(c) for c in candidates) or "none",
        returns=context.get("returns") or "XIRR not known.",
        news_trust=context.get("news_trust") or "Not measured yet, so its reliability is unknown.",
    )
    system, prompt = render("portfolio_review", **values)
    text = (await llm_service.get_completion(prompt, system_prompt=system, task="portfolio.review") or "").strip()
    parsed = _answer(text)
    if not parsed:
        logger.warning("portfolio review: no usable answer from the model: %.200s", text)

    async def again(found: list[str]):
        retry = (f"{prompt}\n\nYour last answer:\n{text}\n\nThese are not in the facts above or are not plain words: "
                 f"{', '.join(found)}. Answer again in the same JSON, without them.")
        reply = await llm_service.get_completion(retry, system_prompt=system, task="portfolio.review")
        nonlocal parsed
        redo = _answer(reply)
        if not _fields(redo):
            return None
        parsed = redo
        return _fields(redo)

    checked = await check_fields(_fields(parsed), [*values.values(), TAX_FACTS], again)
    return {"summary": checked.get("summary"), "plan": checked.get("plan"),
            "notes": {k[5:]: v for k, v in checked.items() if k.startswith("note:")},
            "calls": valid_calls(parsed.get("calls"), rows, candidates)}
