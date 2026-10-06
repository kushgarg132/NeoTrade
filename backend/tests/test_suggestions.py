"""AI suggestions: the human-in-the-loop gate for long-term trades.

INTRADAY signals still execute themselves -- a person cannot sit on a 5m
bar -- while LONGTERM signals stop at a PENDING suggestion carrying the
sizing, stop, target and reason codes the engine already computed, and wait
for an explicit approve or reject.
"""

from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Intent, Order, Side
from backend.engine.runner import Proposal
from backend.scoring.composite import CompositeScore
from backend.suggestions.sink import SuggestionSink
from backend.suggestions.store import SuggestionStore

NOW = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def mongo():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture
def store(mongo):
    return SuggestionStore(mongo)


def _proposal(mode: str = "LONGTERM", symbol: str = "RELIANCE") -> Proposal:
    return Proposal(
        order=Order(
            id="o1", symbol=symbol, side=Side.BUY, quantity=12.0,
            order_type="MARKET", limit_price=None,
            product="CNC" if mode == "LONGTERM" else "MIS",
        ),
        intent=Intent(
            symbol=symbol, side=Side.BUY, strength=0.8,
            reason_codes=["macd_cross", "volume_confirm"],
            stop_hint=95.0, target_hint=130.0,
        ),
        score=CompositeScore(rule_score=0.8, ai_score=0.4),
        entry=100.0,
        mode=mode,
    )


async def _create(store, **overrides) -> dict:
    payload = dict(user_id="alice", proposal=_proposal(), source="run", run_id="run-1")
    payload.update(overrides)
    return await store.create(**payload)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_persists_the_engines_own_numbers(store):
    suggestion = await _create(store)

    assert suggestion["status"] == "PENDING"
    assert suggestion["symbol"] == "RELIANCE"
    assert suggestion["mode"] == "LONGTERM"
    assert suggestion["side"] == "BUY"
    assert suggestion["quantity"] == 12.0
    assert suggestion["entry_ref"] == 100.0
    assert suggestion["stop"] == 95.0
    assert suggestion["target"] == 130.0
    assert suggestion["reason_codes"] == ["macd_cross", "volume_confirm"]
    assert suggestion["score"]["rule"] == 0.8
    assert suggestion["score"]["ai"] == 0.4
    assert suggestion["score"]["final"] == pytest.approx(CompositeScore(rule_score=0.8, ai_score=0.4).final)
    assert suggestion["notional"] == pytest.approx(1200.0)
    assert suggestion["ai_thesis"] is None
    assert suggestion["option_contract"] is None


def _option_proposal() -> Proposal:
    return Proposal(
        order=Order(
            id="o2", symbol="RELIANCE24DEC2800PE", side=Side.SELL, quantity=250.0,
            order_type="MARKET", limit_price=None, product="NRML",
        ),
        intent=Intent(
            symbol="RELIANCE", side=Side.SELL, strength=0.8, reason_codes=["oversold_csp"],
            option_flavor="CSP",
        ),
        score=CompositeScore(rule_score=0.8, ai_score=0.0),
        entry=45.0,
        mode="LONGTERM",
        option_contract={
            "strike": 2760.0, "expiry": "2024-12-26T00:00:00", "option_type": "PE",
            "lot_size": 250, "premium_estimate": 45.0, "margin_estimate": 82800.0,
            "underlying_spot": 2900.0,
        },
    )


@pytest.mark.asyncio
async def test_create_persists_option_contract_when_present(store):
    suggestion = await store.create(user_id="alice", proposal=_option_proposal(), source="run", run_id="run-1")
    assert suggestion["option_contract"]["strike"] == 2760.0
    assert suggestion["option_contract"]["option_type"] == "PE"


@pytest.mark.asyncio
async def test_listing_filters_by_mode_and_status(store):
    await _create(store)
    await _create(store, proposal=_proposal(mode="INTRADAY", symbol="TCS"))

    assert len(await store.list("alice")) == 2
    assert [s["symbol"] for s in await store.list("alice", mode="INTRADAY")] == ["TCS"]
    assert len(await store.list("alice", status="PENDING")) == 2
    assert await store.list("alice", status="REJECTED") == []


@pytest.mark.asyncio
async def test_suggestions_are_isolated_per_user(store):
    await _create(store)
    assert await store.list("bob") == []


@pytest.mark.asyncio
async def test_decide_records_the_outcome(store):
    suggestion = await _create(store)

    decided = await store.decide("alice", suggestion["id"], status="REJECTED", reason="too extended")

    assert decided["status"] == "REJECTED"
    assert decided["reason"] == "too extended"
    assert decided["decided_at"] is not None
    assert await store.list("alice", status="PENDING") == []


@pytest.mark.asyncio
async def test_decide_refuses_a_suggestion_owned_by_someone_else(store):
    suggestion = await _create(store)
    assert await store.decide("bob", suggestion["id"], status="REJECTED") is None


@pytest.mark.asyncio
async def test_decide_refuses_an_already_decided_suggestion(store):
    """Double-clicking Approve must not place a second order."""
    suggestion = await _create(store)
    await store.decide("alice", suggestion["id"], status="REJECTED")

    assert await store.decide("alice", suggestion["id"], status="APPROVED") is None


@pytest.mark.asyncio
async def test_attach_thesis_patches_the_pending_suggestion(store):
    suggestion = await _create(store)

    await store.attach_thesis("alice", suggestion["id"], "Margins recovering for three quarters.")

    assert (await store.get("alice", suggestion["id"]))["ai_thesis"].startswith("Margins recovering")


@pytest.mark.asyncio
async def test_expire_stale_only_touches_pending_ones_past_their_date(store):
    fresh = await _create(store, expires_at=NOW + timedelta(days=1))
    stale = await _create(store, expires_at=NOW - timedelta(days=1))

    expired = await store.expire_stale(now=NOW)

    assert expired == 1
    assert (await store.get("alice", stale["id"]))["status"] == "EXPIRED"
    assert (await store.get("alice", fresh["id"]))["status"] == "PENDING"


@pytest.mark.asyncio
async def test_only_the_best_few_long_term_proposals_stay_pending(store):
    made = []
    for i, final in enumerate([0.5, 0.9, 0.7, 0.6, 0.8]):
        doc = await _create(store, proposal=_proposal(symbol=f"S{i}"))
        await store.collection.update_one({"id": doc["id"]}, {"$set": {"score.final": final}})
        made.append(doc["id"])
    intraday = await _create(store, proposal=_proposal(mode="INTRADAY", symbol="X"))

    assert await store.keep_best("alice", "LONGTERM", 3, now=NOW) == 2
    status = {i: (await store.get("alice", i))["status"] for i in made}
    assert [status[i] for i in made] == ["EXPIRED", "PENDING", "PENDING", "EXPIRED", "PENDING"]
    assert (await store.get("alice", made[0]))["expired_reason"] == "outranked"
    assert (await store.get("alice", intraday["id"]))["status"] == "PENDING"  # other modes untouched


@pytest.mark.asyncio
async def test_an_expired_proposal_cannot_be_approved_before_the_sweep(store):
    stale = await _create(store, expires_at=NOW - timedelta(minutes=1))
    assert await store.decide("alice", stale["id"], status="SENDING", now=NOW) is None
    # Declining it is still fine: nothing is sent.
    assert (await store.decide("alice", stale["id"], status="REJECTED", now=NOW))["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# The engine seam
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sink_diverts_longterm_orders_into_suggestions(store):
    sink = SuggestionSink(store, user_id="alice", run_id="run-1")

    executed = await sink(_proposal(mode="LONGTERM"))

    assert executed is False, "a long-term order must wait for approval, not execute"
    assert len(await store.list("alice", status="PENDING")) == 1


@pytest.mark.asyncio
async def test_sink_lets_intraday_orders_through_untouched(store):
    sink = SuggestionSink(store, user_id="alice", run_id="run-1")

    executed = await sink(_proposal(mode="INTRADAY"))

    assert executed is True
    assert await store.list("alice") == [], "intraday trades are not gated on a human"
