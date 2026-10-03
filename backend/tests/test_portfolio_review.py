"""Portfolio phases 3-5: stock health, rule-scored verdicts through the one
conviction formula, the AI write-up, the admin/all verdict switch, the
stale-holdings fallback and the weekly alert."""

from datetime import date, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.core.models import Holding
from backend.portfolio import review, service
from backend.portfolio.health import price_trend, profit_trend
from backend.portfolio.rules import fund_verdict, stock_verdict, worsened
from backend.routers.portfolio import present

LIMITS = {"max_loss_pct": 25.0, "max_weight_pct": 20.0}


def _health(close=100.0, sma50=None, sma200=None, profits=(), roe=None, pe=None, debt=None):
    return {"trend": {"close": close, "sma_50": sma50, "sma_200": sma200},
            "fundamentals": {"quarterly_profit": list(profits), "roe": roe, "pe": pe, "debt_to_equity": debt}}


def test_profit_and_price_trend():
    assert profit_trend([4, 3, 2, 1]) == "rising" and profit_trend([1, 2, 3, 4]) == "falling"
    assert profit_trend([1, 3, 2, 4]) is None and profit_trend([1, 2]) is None
    trend = price_trend([float(i) for i in range(1, 251)])
    assert trend["sma_50"] == pytest.approx(225.5) and trend["below_high_pct"] == 0
    assert trend["return_3m_pct"] == pytest.approx((250 - 188) / 188 * 100)


def test_one_rule_alone_is_a_hold_two_strong_ones_a_sell():
    row = {"symbol": "X", "pnl_pct": -30.0, "weight_pct": 5.0}
    alone = stock_verdict(row, _health(), LIMITS, None)
    assert alone["verdict"] == "HOLD" and alone["reason_codes"] == ["loss_beyond_limit"]

    two = stock_verdict(row, _health(close=90, sma200=100, profits=(1, 2, 3, 4)), LIMITS, None)
    assert two["verdict"] == "SELL"
    assert two["reason_codes"] == ["loss_beyond_limit", "earnings_falling_3q", "below_200dma"]
    assert two["score"]["rule"] == pytest.approx(0.85)


def test_ai_cannot_make_a_verdict_and_moves_conviction_at_most_thirty_percent():
    row = {"symbol": "X", "pnl_pct": -30.0, "weight_pct": 5.0}
    # Terrible news on a single-rule holding: still HOLD, AI cannot rescue it.
    assert stock_verdict(row, _health(), LIMITS, -1.0)["verdict"] == "HOLD"
    weak = _health(close=90, sma200=100)  # loss + below 200dma = 0.55
    good_news = stock_verdict(row, weak, LIMITS, 1.0)["score"]["final"]
    bad_news = stock_verdict(row, weak, LIMITS, -1.0)["score"]["final"]
    assert bad_news > good_news  # bad news supports a sell, good news argues against it
    assert bad_news - good_news == pytest.approx(0.30)


def test_add_needs_room_under_the_size_limit():
    healthy = _health(close=120, sma50=110, sma200=100, profits=(4, 3, 2, 1), roe=0.2, pe=25)
    assert stock_verdict({"symbol": "Y", "pnl_pct": 10.0, "weight_pct": 8.0}, healthy, LIMITS, None)["verdict"] == "ADD"
    full = stock_verdict({"symbol": "Y", "pnl_pct": 10.0, "weight_pct": 22.0}, healthy, LIMITS, None)
    assert full["verdict"] == "HOLD" and full["reason_codes"] == ["overweight"]


def test_funds_get_review_or_keep():
    assert fund_verdict({"pnl_pct": -30.0, "weight_pct": 5.0}, LIMITS)["verdict"] == "REVIEW"
    assert fund_verdict({"pnl_pct": 5.0, "weight_pct": 30.0}, LIMITS)["verdict"] == "KEEP"


def test_worsened_only_counts_new_trouble():
    assert worsened("HOLD", "SELL") and worsened("KEEP", "REVIEW") and worsened("ADD", "SELL")
    assert not worsened("SELL", "SELL") and not worsened(None, "SELL") and not worsened("SELL", "HOLD")


def test_non_admins_see_facts_and_review_first_not_verdicts():
    snapshot = {"_id": 1, "raw_holdings": [], "holdings": [
        {"symbol": "A", "verdict": "SELL", "previous_verdict": "HOLD", "score": {"final": 0.7}, "reason_codes": ["x"]},
        {"symbol": "B", "verdict": "ADD", "previous_verdict": None, "score": {"final": 0.6}, "reason_codes": ["y"]},
    ]}
    masked = present(snapshot, show_verdicts=False)
    assert "raw_holdings" not in masked and masked["verdicts_visible"] is False
    assert [(r["verdict"], r["previous_verdict"], r["score"]) for r in masked["holdings"]] == [
        ("REVIEW", None, None), (None, None, None),
    ]
    assert masked["holdings"][0]["reason_codes"] == ["x"]
    assert present(snapshot, show_verdicts=True)["holdings"][0]["verdict"] == "SELL"


async def test_write_up_parses_the_models_json_and_survives_garbage(monkeypatch):
    card = {"totals": {"value": 1, "invested": 1, "pnl_pct": 0, "day_change": 0},
            "benchmark": {"covered_pct": None, "portfolio_pct": None, "nifty_pct": None},
            "concentration": {"top_symbol": "A", "top_pct": 100, "top5_pct": 100, "effective_holdings": 1,
                              "sectors": [], "correlated": []},
            "holdings": [{"symbol": "A", "kind": "STOCK", "reason_codes": []}]}
    answers = iter(['Sure! {"summary": "### How it is doing\\nFine", "notes": {"A": "Steady."}}', "LLM_DISABLED"])
    monkeypatch.setattr(review.llm_service, "get_completion", AsyncMock(side_effect=lambda *a, **k: next(answers)))
    assert await review.write_review(card) == {"summary": "### How it is doing\nFine", "notes": {"A": "Steady."}, "plan": None}
    assert await review.write_review(card) == {"summary": None, "notes": {}, "plan": None}


def _patch_sources(monkeypatch, brokers, closes=None):
    monkeypatch.setattr(service, "get_broker_adapter", AsyncMock(side_effect=lambda b, *a: brokers[b]))
    monkeypatch.setattr(service, "_nifty", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_sector_sync", lambda ticker: "Energy")
    monkeypatch.setattr(service, "_daily_closes_sync", lambda tickers: closes or {})
    monkeypatch.setattr(service, "stock_health", AsyncMock(side_effect=lambda db, rows, closes, now: {
        r["symbol"]: _health(close=90, sma200=100) if r["symbol"] == "A" else _health() for r in rows}))
    monkeypatch.setattr(service, "write_review", AsyncMock(return_value={"summary": "S", "notes": {"A": "n"}}))


class _Broker:
    def __init__(self, holdings=None, active=True):
        self.holdings, self.active = holdings or [], active

    async def state(self):
        from backend.brokers.protocol import BrokerSessionState
        return BrokerSessionState.ACTIVE if self.active else BrokerSessionState.NEEDS_LOGIN

    async def get_holdings(self):
        return self.holdings


def _h(symbol, avg, last):
    return Holding(symbol=symbol, isin=symbol, quantity=10, avg_price=avg, last_price=last, broker="kite")


async def test_refresh_reviews_every_holding_and_remembers_the_last_verdict(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    kite = _Broker([_h("A", 100, 70), _h("B", 100, 105)])
    _patch_sources(monkeypatch, {"kite": kite, "upstox": _Broker(active=False), "angel_one": _Broker(active=False)})

    first = await service.refresh_portfolio(db, "alice", None, None)
    rows = {r["symbol"]: r for r in first["holdings"]}
    assert rows["A"]["verdict"] == "SELL" and rows["A"]["note"] == "n" and first["summary"] == "S"
    assert rows["B"]["verdict"] == "HOLD" and rows["A"]["previous_verdict"] is None

    second = await service.refresh_portfolio(db, "alice", None, None)
    assert {r["symbol"]: r["previous_verdict"] for r in second["holdings"]} == {"A": "SELL", "B": "HOLD"}


async def test_without_a_session_the_last_holdings_are_reused_and_repriced(monkeypatch):
    db = AsyncMongoMockClient()["test_db"]
    kite = _Broker([_h("A", 100, 70)])
    brokers = {"kite": kite, "upstox": _Broker(active=False), "angel_one": _Broker(active=False)}
    today = date(2026, 9, 25)
    _patch_sources(monkeypatch, brokers, closes={"A": [(today - timedelta(days=1), 80.0), (today, 82.0)]})
    first = await service.refresh_portfolio(db, "alice", None, None, analyse=False)
    assert first["stale_since"] is None

    kite.active = False
    second = await service.refresh_portfolio(db, "alice", None, None, analyse=False)
    stale = second["stale_since"].replace(tzinfo=timezone.utc)
    assert abs(stale - first["at"]) < timedelta(seconds=1)
    assert second["totals"]["value"] == 820 and second["totals"]["day_change"] == 20


async def test_weekly_review_alerts_only_on_a_worse_verdict(monkeypatch):
    from backend.guardrails.store import GuardrailStore
    from backend.ws.hub import hub

    db = AsyncMongoMockClient()["test_db"]
    await db["users"].insert_one({"id": "alice", "role": "user"})
    await GuardrailStore(db).set_telegram_chat("alice", 42)
    kite = _Broker([_h("A", 100, 110)])
    _patch_sources(monkeypatch, {"kite": kite, "upstox": _Broker(active=False), "angel_one": _Broker(active=False)})
    monkeypatch.setattr(service, "stock_health", AsyncMock(
        side_effect=lambda db, rows, closes, now: {r["symbol"]: _health() for r in rows}))
    await service.refresh_portfolio(db, "alice", None, None)  # HOLD

    kite.holdings = [_h("A", 100, 70)]  # now 30% down and below its 200-day average
    monkeypatch.setattr(service, "stock_health", AsyncMock(
        side_effect=lambda db, rows, closes, now: {r["symbol"]: _health(close=90, sma200=100) for r in rows}))
    sent = []
    monkeypatch.setattr("backend.guardrails.telegram.send", AsyncMock(side_effect=lambda chat, text: sent.append((chat, text))))
    monkeypatch.setattr(hub, "publish", AsyncMock())
    monkeypatch.setattr("backend.auth.broker_credentials.fernet_from_settings", lambda: None)

    assert await service.weekly_reviews(db, None) == 1
    ((chat, text),) = sent
    assert chat == 42 and "A: worth a closer look" in text and "SELL" not in text  # not an admin
    assert await service.weekly_reviews(db, None) == 1 and len(sent) == 1  # still SELL: no repeat alert


def test_non_admins_do_not_see_the_action_plan():
    snapshot = {"holdings": [], "plan": "### Sell or trim\n- A"}
    assert present(snapshot, show_verdicts=False)["plan"] is None
    assert present(snapshot, show_verdicts=True)["plan"] == "### Sell or trim\n- A"


async def test_write_up_returns_the_plan_and_sends_the_candidates(monkeypatch):
    card = {"totals": {"value": 1, "invested": 1, "pnl_pct": 0, "day_change": 0},
            "benchmark": {"covered_pct": None, "portfolio_pct": None, "nifty_pct": None},
            "concentration": {"top_symbol": "A", "top_pct": 100, "top5_pct": 100, "effective_holdings": 1,
                              "sectors": [], "correlated": []},
            "holdings": [{"symbol": "A", "kind": "STOCK", "reason_codes": []}]}
    llm = AsyncMock(return_value='{"summary": "S", "notes": {}, "plan": "### Add\\n- NEWCO"}')
    monkeypatch.setattr(review.llm_service, "get_completion", llm)
    candidates = [{"symbol": "NEWCO", "score": {"final": 0.62}, "reason_codes": ["quality_momentum"], "ai_thesis": None}]
    assert (await review.write_review(card, candidates))["plan"] == "### Add\n- NEWCO"
    assert "NEWCO" in llm.call_args.args[0] and "quality_momentum" in llm.call_args.args[0]


async def test_add_candidates_are_recent_scanned_buys_not_already_held():
    from datetime import datetime
    db = AsyncMongoMockClient()["test_db"]
    now = datetime.now(timezone.utc)

    def s(symbol, final, days_ago=0, side="BUY", mode="LONGTERM", status="PENDING", user="alice"):
        return {"user_id": user, "symbol": symbol, "side": side, "mode": mode, "status": status,
                "score": {"final": final}, "reason_codes": ["r"], "ai_thesis": None,
                "created_at": now - timedelta(days=days_ago)}

    await db["suggestions"].insert_many([
        s("HELD", 0.9), s("OLD", 0.9, days_ago=10), s("SHORT", 0.9, side="SELL"), s("INTRA", 0.9, mode="INTRADAY"),
        s("NOPE", 0.9, status="REJECTED"), s("OTHER", 0.9, user="bob"),
        s("LOW", 0.5), s("TOP", 0.8), s("TOP", 0.7),
    ])
    picks = await service.add_candidates(db, "alice", held={"HELD"}, now=now)
    assert [p["symbol"] for p in picks] == ["TOP", "LOW"]
