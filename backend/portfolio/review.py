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

from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)

# ponytail: one LLM call, the largest holdings only; batch the notes if
# portfolios this size start losing detail.
MAX_HOLDINGS = 40


def _fmt(value, suffix="") -> str:
    return "n/a" if value is None else f"{value:,.2f}{suffix}"


def _holding_line(row: dict) -> str:
    health = row.get("health") or {}
    trend, fundamentals = health.get("trend") or {}, health.get("fundamentals") or {}
    headlines = "; ".join(h["title"] for h in (health.get("headlines") or [])[:3]) or "none"
    return (
        f"- {row['symbol']} ({row['kind']}{', ' + row['sector'] if row.get('sector') else ''}): "
        f"{_fmt(row.get('weight_pct'), '%')} of portfolio, P&L {_fmt(row.get('pnl_pct'), '%')}, "
        f"NIFTY same days {_fmt(row.get('nifty_pnl_pct'), '%')}. Reason codes: {', '.join(row['reason_codes']) or 'none'}. "
        f"Price {_fmt(trend.get('close'))}, 50d {_fmt(trend.get('sma_50'))}, 200d {_fmt(trend.get('sma_200'))}, "
        f"{_fmt(trend.get('below_high_pct'), '%')} below 52w high, 3m {_fmt(trend.get('return_3m_pct'), '%')}. "
        f"P/E {_fmt(fundamentals.get('pe'))}, ROE {_fmt(fundamentals.get('roe'))}, debt/equity "
        f"{_fmt(fundamentals.get('debt_to_equity'))}, last 4 quarters' profit (newest first) "
        f"{fundamentals.get('quarterly_profit') or 'n/a'}. Headlines: {headlines}"
    )


def _candidate_line(c: dict) -> str:
    thesis = str(c.get("ai_thesis") or "")[:200]
    return (
        f"- {c['symbol']}: score {_fmt((c.get('score') or {}).get('final'))}, "
        f"reasons {', '.join(c.get('reason_codes') or []) or 'none'}" + (f". Thesis: {thesis}" if thesis else "")
    )


async def write_review(card: dict, candidates: list[dict] | None = None) -> dict:
    """{"summary": markdown or None, "notes": {symbol: text}, "plan": markdown or None}. A model that
    is off or answers badly leaves the review without prose, never fails it."""
    totals, bench, conc = card["totals"], card["benchmark"], card["concentration"]
    rows = card["holdings"][:MAX_HOLDINGS]
    system, prompt = render(
        "portfolio_review",
        totals=(
            f"Value {_fmt(totals['value'])}, invested {_fmt(totals['invested'])}, gain {_fmt(totals['pnl_pct'], '%')}, "
            f"today {_fmt(totals['day_change'])}. Against NIFTY on the {_fmt(bench['covered_pct'], '%')} of money "
            f"with known buy dates: holdings {_fmt(bench['portfolio_pct'], '%')}, NIFTY {_fmt(bench['nifty_pct'], '%')}."
        ),
        concentration=(
            f"Largest {conc['top_symbol']} at {_fmt(conc['top_pct'], '%')}; top five {_fmt(conc['top5_pct'], '%')}; "
            f"weighted like {_fmt(conc['effective_holdings'])} equal holdings. Sectors: "
            + ", ".join(f"{s['sector']} {s['pct']:.1f}%" for s in conc["sectors"])
            + ". Moving together: " + (", ".join(f"{p['a']}/{p['b']} {p['correlation']}" for p in conc["correlated"]) or "none")
        ),
        holdings="\n".join(_holding_line(r) for r in rows),
        candidates="\n".join(_candidate_line(c) for c in candidates or []) or "none",
    )
    text = (await llm_service.get_completion(prompt, system_prompt=system) or "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    try:
        parsed = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        parsed = {}
    if not parsed:
        logger.warning("portfolio review: no usable answer from the model: %.200s", text)
    notes = parsed.get("notes") if isinstance(parsed.get("notes"), dict) else {}
    summary = parsed.get("summary") if isinstance(parsed.get("summary"), str) else None
    plan = parsed.get("plan") if isinstance(parsed.get("plan"), str) else None
    return {"summary": summary, "notes": {k: v for k, v in notes.items() if isinstance(v, str)}, "plan": plan}
