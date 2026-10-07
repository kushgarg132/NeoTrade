"""Mid-session revisions of the game plan (ingest loop, 60 s, leader only).

Triggers: a material scored item on a planned or held symbol or its sector,
a `market:regime` label change, a high-impact calendar event passing. Per
user at most MAX_REVISIONS a day, MIN_GAP apart; triggers that land while a
user is rate-limited are dropped (the next revision sees the market as it
is then). A revision is one `deep` call returning the full plan, validated
like the pre-open one and stored as a new version, which running engines
pick up on their next bar (exits, stocks in play). Fallback plans are never
revised."""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from backend.engine.session import IST, clock
from backend.plan import store
from backend.plan.validate import validate

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2  # each is a deep call; was 6 before Phase 17.2.4
MIN_GAP = timedelta(minutes=15)
REGIME_SEEN = "plan:regime_seen"
EVENT_KEY = "plan:event:{}"
NOT_REVISIONS = {"pre_open", "fallback"}


async def _held(db, user_id: str) -> dict[str, float]:
    from backend.engine.persistence import LedgerStore

    positions = await LedgerStore(db, user_id=user_id).get_open_positions(venue="paper")
    return {s: p.quantity for s, p in positions.items()}


async def triggers(db, redis, plans: dict[str, dict], now: datetime) -> dict[str, list[tuple[str, str]]]:
    """user_id -> [(trigger code, description)] for this pass."""
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.datalayer.reactor import _claim

    out: dict[str, list[tuple[str, str]]] = {}
    sector_of = nifty200_sectors()

    items = await _claim(db, "planned_at", now)
    for user_id, plan in plans.items():
        names = set(plan.get("scope") or []) | set(await _held(db, user_id))
        sectors = {sector_of[s] for s in names if s in sector_of}
        for item in items:
            hits = [i for i in item.get("impacts") or []
                    if (i.get("type") == "symbol" and i.get("target") in names)
                    or (i.get("type") == "sector" and i.get("target") in sectors)]
            if hits:
                top = max(hits, key=lambda i: i.get("impact", 0))
                out.setdefault(user_id, []).append((f"news:{item['_id']}", (
                    f"News: {item.get('event') or item.get('title')} -> {top['target']} "
                    f"{top['direction']:+.1f} (impact {top['impact']:.0f}/10)")))

    raw = await redis.get("market:regime")
    label = (json.loads(raw) or {}).get("label") if raw else None
    if label:
        seen = await redis.get(REGIME_SEEN)
        seen = seen.decode() if isinstance(seen, bytes) else seen
        await redis.set(REGIME_SEEN, label, ex=86400)
        if seen and seen != label:
            for user_id in plans:
                out.setdefault(user_id, []).append(("regime_flip", f"Market regime changed: {seen} -> {label}"))

    events = await db["econ_calendar"].find({
        "impact": "High", "at": {"$gte": now - timedelta(minutes=15), "$lte": now - timedelta(minutes=5)},
    }).to_list(length=20)
    for event in events:
        if await redis.set(EVENT_KEY.format(event["_id"]), "1", ex=86400, nx=True):
            for user_id in plans:
                out.setdefault(user_id, []).append(("event_passed", (
                    f"High-impact event just passed: {event.get('country', '')} {event.get('title', '')}")))
    return out


async def may_revise(db, user_id: str, day: date, now: datetime) -> bool:
    versions = await store.versions(db, user_id, day)
    if not versions:
        return False
    if sum(v["trigger"] not in NOT_REVISIONS for v in versions) >= MAX_REVISIONS:
        return False
    return max(v["at"] for v in versions) <= now - MIN_GAP


async def revise_plan(db, redis, user_id: str, plan: dict, reasons: list[tuple[str, str]], now: datetime,
                      complete=None, llm=None) -> Optional[dict]:
    from backend.datalayer.news_sources import nifty200_sectors
    from backend.learning.library import _strategies
    from backend.plan import builder
    from backend.prompts import render

    day = now.astimezone(IST).date()
    cards = [{"name": s.spec.name, **{k: getattr(s.CARD, k) for k in ("style", "regimes", "needs")}}
             for s in _strategies(user_id) if s.spec.mode == "INTRADAY"]
    names = {c["name"] for c in cards}
    raw = await redis.get("market:regime")
    regime = json.loads(raw) if raw else {}
    current = {k: plan.get(k) for k in ("allow", "add_symbols", "risk_multiplier", "max_positions", "skip_day",
                                         "rationale")}
    scope, adds = set(plan.get("scope") or []), set(plan.get("add_symbols") or [])
    values = dict(
        now=f"{now.astimezone(IST):%a %d %b %Y} {clock(now)} IST",
        trigger="\n".join(f"- {text}" for _, text in reasons),
        regime=f"{regime.get('label', 'unknown')} ({regime.get('score', 0):+.2f})",
        # Only names the plan covers: never a long-term holding or a hand trade elsewhere.
        plan=json.dumps(current),
        positions=json.dumps({s: q for s, q in (await _held(db, user_id)).items() if s in scope}),
        strategies=json.dumps(cards),
    )

    def checked(reply) -> Optional[object]:
        try:
            return validate(reply, trigger=reasons[0][0], strategies=names, universe=scope - adds,
                            nifty200=set(nifty200_sectors()))
        except (ValueError, TypeError, OverflowError) as exc:
            logger.info("plan revision for %s: unreadable reply (%s)", user_id, exc)
            return None

    revised = None
    if complete is None:  # production: facts through tools first, the single call as fallback
        revised = await _revise_with_tools(db, redis, user_id, values, day, checked, llm)
        complete = builder._llm
    if revised is None:
        if not await store.reserve_call(redis, day):
            logger.info("plan revision for %s skipped: daily AI plan budget used up", user_id)
            return None
        system, prompt = render("game_plan_revision", **values)
        reply = (await complete(system, prompt) or "").strip()
        if not reply or reply == "LLM_DISABLED" or reply.startswith("Error generating response"):
            logger.info("plan revision for %s: AI unavailable, current plan stands", user_id)
            return None
        revised = checked(reply)
        if revised is None:
            return None
    # Scope never shrinks within a day: a dropped add stays judged (and, no
    # longer in allow, blocked) rather than falling outside the gate.
    revised.scope = sorted(set(revised.scope) | scope)
    doc = await store.save(db, redis, user_id, day, revised, now)
    logger.info("plan revised for %s: v%d (%s)", user_id, doc["version"], reasons[0][0])
    await builder._tell(db, user_id, doc)
    return doc


async def _revise_with_tools(db, redis, user_id: str, values: dict, day, checked, llm=None):
    """The revised plan from the tool loop, or None to use the single call."""
    from backend.ai.facts import as_tools
    from backend.ai.runner import run_with_tools
    from backend.plan.builder import MAX_TOOL_ROUNDS, PlanReply, _seed_values, ground_rationale
    from backend.prompts import render

    system, prompt = render("game_plan_revision_tools", **values)
    tools = as_tools(db, redis, user_id, ["news", "price_summary", "positions"])
    out = await run_with_tools("plan_revision", system=system, prompt=prompt, tools=tools, tier="deep", feature="plan",
                               schema=PlanReply, llm=llm, max_rounds=MAX_TOOL_ROUNDS,
                               reserve=lambda: store.reserve_call(redis, day))
    if not isinstance(out["output"], PlanReply):
        return None
    revised = checked(out["output"].model_dump())
    # Exiting while allowing nothing new is a real revision; allowing nothing,
    # exiting nothing and not skipping the day is an empty reply.
    if revised is not None and not revised.allow and not revised.skip_day and not revised.exits:
        logger.info("plan revision for %s: empty tool reply; unusable", user_id)
        return None
    if revised is not None:
        revised.rationale = ground_rationale(revised.rationale, out["facts"] + _seed_values(values))
    return revised


async def loop(db, redis, now: Optional[datetime] = None) -> int:
    from backend.engine.autorun import in_session

    now = now or datetime.now(timezone.utc)
    if not in_session(now):
        return 0
    day = now.astimezone(IST).date()
    plans = {}
    for user_id in await db[store.COLLECTION].distinct("user_id", {"date": day.isoformat()}):
        plan = await store.current(redis, user_id, day)
        if plan and plan.get("trigger") != "fallback":
            plans[user_id] = plan
    if not plans:
        return 0
    made = 0
    for user_id, reasons in (await triggers(db, redis, plans, now)).items():
        try:
            if await may_revise(db, user_id, day, now) and await revise_plan(db, redis, user_id, plans[user_id],
                                                                              reasons, now):
                made += 1
        except Exception as exc:
            logger.exception("plan revision failed for %s: %s", user_id, exc)
    return made
