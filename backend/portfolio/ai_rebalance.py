"""The AI's final rebalance list: the model weighs verdicts, scores, notes,
headlines, tax and the formula's own plan, and answers with a target weight
per stock. It never sizes a trade: its targets are clamped to the user's caps
(`clamp_targets`) and run through the same `rebalance.plan_rebalance` as
overrides, so quantities, charges, tax and the after-view stay code's.
Prompt: backend/prompts/rebalance_ai.md. Same audience as the verdicts.
"""

import asyncio
import json
import logging
import math
import re
from collections import defaultdict

from backend.llm import llm_service
from backend.portfolio.rebalance import sell_tax
from backend.portfolio.review import _fmt, _holding_line
from backend.prompts import render

logger = logging.getLogger(__name__)

RESULTS_DAYS = 30  # a results date further out than this is not a reason to act now
MAX_HOLDINGS = 40  # ponytail: one call, largest holdings first; batch if bigger books lose detail


def clamp_targets(raw, sector_of: dict, targets: dict) -> dict[str, float]:
    """The model's {symbol: percent}, made safe: known symbols only, 0 to the
    stock cap, each sector scaled down to its cap, all together at most 100."""
    stock_cap = float(targets.get("max_stock_pct", 100))
    sector_cap = float(targets.get("max_sector_pct", 100))
    out = {s: min(max(float(v), 0.0), stock_cap) for s, v in (raw if isinstance(raw, dict) else {}).items()
           if s in sector_of and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    by_sector = defaultdict(float)
    for s, v in out.items():
        if sector_of[s]:
            by_sector[sector_of[s]] += v
    for sector, total in by_sector.items():
        if total > sector_cap:
            for s in out:
                if sector_of[s] == sector:
                    out[s] *= sector_cap / total
    total = sum(out.values())
    if total > 100:
        out = {s: v * 100 / total for s, v in out.items()}
    return {s: round(v, 2) for s, v in out.items()}


async def news_context(db, redis, symbols: list[str], results: dict | None = None) -> dict[str, dict]:
    """{symbol: {"sentiment": -1..1 or None, "results": "YYYY-MM-DD" or None}} through the fact layer.
    None sentiment means the cache has nothing (no news), never a neutral 0. `results`: dates already
    read (the router reads them for the trade rows), else read here."""
    from backend.ai.facts.market import next_results, sentiment

    if results is None:
        results = (await next_results(db, redis, None, symbols=symbols, days=RESULTS_DAYS)).get("dates", {})
    reads = await asyncio.gather(*(sentiment(db, redis, None, symbol=s) for s in symbols))
    return {s: {"sentiment": r.get("stock"), "results": results.get(s)} for s, r in zip(symbols, reads)}


def _news_part(n: dict | None) -> str:
    n = n or {}
    news = "no news" if n.get("sentiment") is None else f"news sentiment {n['sentiment']:+.2f}"
    return f"{news}, " + (f"next results {n['results']}" if n.get("results") else f"no results date in {RESULTS_DAYS} days")


def _tax_line(row: dict, lots: list, today) -> str:
    price, qty = row.get("last_price") or row.get("close_price"), row.get("quantity")
    if not price or not qty:
        return "tax if sold: n/a"
    t = sell_tax(qty, price, lots, today)
    if t["est_tax"] is None:
        return "tax if sold: unknown (no dated buys in the journal)"
    return (f"tax if all sold: short-term gain {_fmt(t['short_gain'])}, long-term gain {_fmt(t['long_gain'])}, "
            f"est. tax {_fmt(t['est_tax'])}" + (f", {t['unknown_qty']:g} undated shares" if t["unknown_qty"] else ""))


def _formula_lines(plan: dict, rule: str) -> str:
    trades = plan["trades"]
    lines = [f"- {t['symbol']}: {t['side']} {t['quantity']} (target {t['target_weight']:.1f}%, now {t['weight_now']:.1f}%)"
             for t in trades] or ["- no trades"]
    tax = plan.get("tax") or {}
    lines.append(f"Estimated tax {_fmt(tax.get('est_tax'))}, charges {_fmt(sum(t['charges'] for t in trades))}.")
    after = plan.get("after") or {}
    lines.append("Sectors after (stocks only): " + (", ".join(f"{s['sector']} {s['weight_now']:.1f}% -> {s['weight_after']:.1f}%"
                                                for s in after.get("sectors", [])) or "n/a"))
    lines.append("By type after: " + (", ".join(f"{t['kind']} {t['weight_now']:.1f}% -> {t['weight_after']:.1f}%"
                                                for t in after.get("types", [])) or "n/a"))
    return "\n".join(lines)


async def ai_targets(holdings: list[dict], context: dict, candidates: list[dict], targets: dict,
                     new_money: float, formula: dict, review_plan, lots: dict, today,
                     news: dict | None = None) -> dict | None:
    """{"targets": {symbol: pct}, "reasons": {symbol: text}, "summary": md}, unclamped,
    or None when the model is off or answers badly. `news`: news_context(), per symbol."""
    news = news or {}
    rows = sorted(holdings, key=lambda r: -(r.get("weight_pct") or 0))[:MAX_HOLDINGS]
    lines = []
    for r in rows:
        full = {**r, **context.get(r["symbol"], {})}
        full.setdefault("reason_codes", [])
        score = (full.get("score") or {}).get("final")
        lines.append(_holding_line(full) + f". Verdict {full.get('verdict') or 'n/a'}, score {_fmt(score)}. "
                     f"AI note: {full.get('note') or 'none'}. {_news_part(news.get(r['symbol']))}. {_tax_line(full, lots.get(r['symbol'], []), today)}")
    cands = "\n".join(f"- {c['symbol']} ({c['source']}): score {_fmt(c.get('score'))}, price {_fmt(c['price'])}, "
                      f"{_news_part(news.get(c['symbol']))}" for c in candidates) or "none"
    system, prompt = render(
        "rebalance_ai", max_stock_pct=targets.get("max_stock_pct", 100), max_sector_pct=targets.get("max_sector_pct", 100),
        new_money=_fmt(new_money), holdings="\n".join(lines), candidates=cands, review_plan=review_plan or "none",
        rule=targets.get("rule", "cap"), results_days=RESULTS_DAYS, formula=_formula_lines(formula, targets.get("rule", "cap")),
    )
    text = (await llm_service.get_completion(prompt, system_prompt=system, tier="deep", feature="portfolio") or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    try:
        parsed = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed.get("targets"), dict) or not parsed["targets"]:
        logger.warning("rebalance ai: no usable answer from the model: %.200s", text)
        return None
    reasons = parsed.get("reasons") if isinstance(parsed.get("reasons"), dict) else {}
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), str) else None
    return {"targets": parsed["targets"], "reasons": {k: v for k, v in reasons.items() if isinstance(v, str)},
            "summary": summary}
