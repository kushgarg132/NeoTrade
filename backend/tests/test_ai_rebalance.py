"""The AI's final rebalance list: caps clamp the model, code sizes the trades."""

from backend.portfolio.ai_rebalance import clamp_targets
from backend.tests.test_portfolio_rebalance_router import _client, _snapshot, _user, mdb  # noqa: F401
from backend.routers import portfolio as portfolio_router

CAPS = {"rule": "cap", "max_stock_pct": 15, "max_sector_pct": 30}


def test_clamp_drops_unknown_symbols_and_bad_values_and_caps_each_stock():
    sector_of = {"A": "IT", "B": "Banks", "N": None}
    out = clamp_targets({"A": 40, "B": -5, "N": "x", "ZZZ": 10, "T": True}, sector_of, CAPS)
    assert out == {"A": 15.0, "B": 0.0}


def test_clamp_scales_a_sector_to_its_cap_and_the_book_to_100():
    sector_of = {"A": "IT", "B": "IT", "C": "IT", **{f"E{i}": None for i in range(8)}}
    out = clamp_targets({"A": 15, "B": 15, "C": 15, **{f"E{i}": 15 for i in range(8)}}, sector_of, CAPS)
    assert abs(out["A"] + out["B"] + out["C"] - 30 * 100 / 150) < 0.05  # IT to 30, then all scaled from 150 to 100
    assert abs(sum(out.values()) - 100) < 0.1
    assert clamp_targets("not a dict", sector_of, CAPS) == {}


async def test_ai_list_is_hidden_from_users_without_verdicts(mdb):  # noqa: F811
    await _snapshot(mdb)
    r = _client(_user()).post("/api/v1/portfolio/rebalance/ai", json={"new_money": 0})
    assert r.status_code == 403


async def test_ai_list_is_capped_and_sized_by_code(mdb, monkeypatch):  # noqa: F811
    await _snapshot(mdb)
    seen = {}

    async def fake(holdings, context, candidates, targets, new_money, formula, plan, lots, today, news=None):
        seen["formula"], seen["news"] = formula, news
        return {"targets": {"A": 90, "B": 15, "C": 15, "NOPE": 20}, "reasons": {"A": "trim", "NOPE": "x"}, "summary": "- s"}

    monkeypatch.setattr("backend.portfolio.ai_rebalance.ai_targets", fake)
    r = _client(_user(role="admin")).post("/api/v1/portfolio/rebalance/ai",
                                          json={"new_money": 0, "targets": {"rule": "cap", "max_stock_pct": 50, "max_sector_pct": 100}})
    body = r.json()
    assert r.status_code == 200
    assert body["targets"] == {"A": 50.0, "B": 15.0, "C": 15.0} and body["reasons"] == {"A": "trim"}
    trades = {t["symbol"]: t for t in body["plan"]["trades"]}
    assert trades["A"]["side"] == "SELL" and "tax" in body["plan"] and "after" in body["plan"]
    assert seen["formula"]["trades"]  # the model saw the formula's own plan
    assert seen["news"]["A"] == {"sentiment": None, "results": None}  # no cache: "no news", not 0
    assert all("next_results" in t for t in body["plan"]["trades"])


async def test_ai_list_says_so_when_the_model_fails(mdb, monkeypatch):  # noqa: F811
    await _snapshot(mdb)

    async def nothing(*a, **kw):
        return None

    monkeypatch.setattr("backend.portfolio.ai_rebalance.ai_targets", nothing)
    r = _client(_user(role="admin")).post("/api/v1/portfolio/rebalance/ai", json={"new_money": 0})
    assert r.status_code == 502


async def test_ai_targets_renders_the_prompt_and_reads_the_answer(monkeypatch):
    from datetime import date

    from backend.portfolio import ai_rebalance
    from backend.portfolio.rebalance import plan_rebalance

    rows = [{"symbol": "A", "kind": "STOCK", "sector": "IT", "quantity": 10, "last_price": 100.0, "close_price": 100.0,
             "weight_pct": 100, "reason_codes": ["overweight"]}]
    formula = plan_rebalance(rows, [], CAPS, 0, {}, date(2026, 10, 26))
    got = {}

    async def complete(prompt, system_prompt=None, **kw):
        got["prompt"] = prompt
        return 'Sure: {"targets": {"A": 10}, "reasons": {"A": "overweight at 100%", "B": 3}, "summary": "- trim A"}'

    monkeypatch.setattr(ai_rebalance.llm_service, "get_completion", complete)
    out = await ai_rebalance.ai_targets(rows, {"A": {"verdict": "SELL", "note": "n1"}},
                                        [{"symbol": "P", "source": "ai", "score": 0.7, "price": 50.0}],
                                        CAPS, 0, formula, None, {}, date(2026, 10, 26),
                                        news={"A": {"sentiment": -0.4, "results": "2026-11-03"}})
    assert out == {"targets": {"A": 10}, "reasons": {"A": "overweight at 100%"}, "summary": "- trim A"}
    assert "Verdict SELL" in got["prompt"] and "P (ai): score 0.70" in got["prompt"] and "at most 15%" in got["prompt"]
    assert "news sentiment -0.40, next results 2026-11-03" in got["prompt"]
    assert "P (ai): score 0.70, price 50.00, no news, no results date in 30 days" in got["prompt"]
    assert "42%" in got["prompt"]

    async def junk(*a, **kw):
        return "no json"

    monkeypatch.setattr(ai_rebalance.llm_service, "get_completion", junk)
    assert await ai_rebalance.ai_targets(rows, {}, [], CAPS, 0, formula, None, {}, date(2026, 10, 26)) is None
