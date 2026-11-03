"""Every LLM prompt lives in backend/prompts/*.md. Each must load, and
rendering must fail loudly on a missing or unknown placeholder."""

from pathlib import Path

import pytest

from backend.prompts import render

PROMPTS = {
    "chat": {"snapshot": "portfolio: value=401747", "page": "/portfolio", "profile": "name=Kush", "view": "Own view allowed"},
    "model_test": {},
    "final_turn": {},
    "resolve_instrument": {"query": "tata motors", "candidates": '[{"tradingsymbol": "TATAMOTORS"}]'},
    "peers": {"name": "Reliance Industries", "symbol": "RELIANCE"},
    "triage_news": {"items": "[0] [GLOBAL] Brent jumps (Reuters)"},
    "score_market_news": {"sectors": "Power, Realty", "items": "[0] (GLOBAL) Brent jumps"},
    "score_news": {"symbol": "SBIN", "articles": "[0] headline"},
    "research_report": {"symbol": "SBIN", "sentiment_score": "-0.20", "relevant_count": 3, "news": "n", "events": "[]", "backdrop": "b",
                        "price": "Last close 800", "fundamentals": "P/E 10", "results": "2026-11-20", "news_trust": "Company 44%"},
    "market_brief": {"now": "Mon", "news": "n", "board": "b", "flows": "f", "regime": "r", "calendar": "c"},
    "game_plan": {"now": "Mon", "regime": "r", "brief": "b", "flows": "f", "calendar": "c", "strategies": "s",
                  "candidates": "c", "caps": "k"},
    "game_plan_tools": {"now": "Mon", "regime": "r", "brief": "b", "flows": "f", "calendar": "c", "strategies": "s",
                        "candidates": "c", "caps": "k"},
    "game_plan_revision": {"now": "Mon", "trigger": "t", "regime": "r", "plan": "p", "positions": "x",
                           "strategies": "s"},
    "game_plan_revision_tools": {"now": "Mon", "trigger": "t", "regime": "r", "plan": "p", "positions": "x",
                                 "strategies": "s"},
    "index_move": {"name": "NIFTY 50", "session_date": "2026-09-26", "session": "- Close 25,123.45",
                   "trend": "- Month +1.2%", "peers": "- SENSEX: -0.40%", "movers": "- HDFCBANK: -1.90%",
                   "headlines": "- RBI holds rates (ET)"},
    "portfolio_review": {"totals": "Value 10,00,000.00", "concentration": "Largest HDFCBANK at 28%",
                         "holdings": "- HDFCBANK (STOCK): reason codes: overweight",
                         "candidates": "- TCS: score 0.62, reasons quality_momentum", "returns": "XIRR 12.00%",
                         "news_trust": "Company news 44%"},
    "rebalance_ai": {"max_stock_pct": 15, "max_sector_pct": 30, "new_money": "0.00", "rule": "cap",
                     "holdings": "- HDFCBANK (STOCK): Verdict ADD, score 0.71", "candidates": "- TCS (ai): score 0.62",
                     "review_plan": "none", "formula": "- HDFCBANK: BUY 5", "results_days": 30, "news_trust": "Company news 44%"},
    "chat_followups": {"question": "Is the engine running?", "answer": "Yes, 166 bars scanned."},
    "learning_review": {"rules": "Paused: vwap", "changes": "vwap: pause False → True",
                        "groups": "vwap / overall: n 30, net ₹-3,000"},
    "strategy_hypotheses": {"strategies": "macd_crossover: runs {'stop_pct': 0.03}", "retunes": "none yet",
                            "setups": "none yet"},
    "strategy_builder": {"vocabulary": "setup gap: direction up | down", "plans": "none yet", "scorecards": "none yet",
                         "library": "[{\"name\": \"orb\"}]", "setups": "none yet", "drafts": "none yet"},
    "strategy_builder_swing": {"vocabulary": "setup breakout_n: days 10..60 step 5",
                               "library": "[{\"name\": \"momentum\"}]", "setups": "none yet", "drafts": "none yet"},
}


# AI summaries (backend/summaries/)
PROMPTS |= {
    "summary_day": {"phase": "after the market has closed", "account": "Your account: ₹2,950", "count": 1,
                    "needs": "- DOWN: HOLD → SELL", "market": "{\"regime\": \"neutral\"}", "sectors": "Basic Materials"},
    "summary_holding": {"item": "{\"kind\": \"bad_news\"}", "position": "{\"weight_pct\": 18.0}", "thesis": "none written", "price": "{\"last_close\": \"₹100.00\"}"},
    "summary_weekly": {"week": "2026-W42", "report": "{}", "patterns": "none", "news": "{}"},
    "summary_habits": {"patterns": "none yet", "week": "{}"},
    "summary_activity": {"day": "Thu 15 Oct 2026", "orders": "none", "rotation": "{\"next rebalance\": \"2026-11-09\"}", "plan": "no plan", "result": "{}"},
}


def test_every_prompt_file_is_covered_here():
    files = {p.stem for p in (Path(__file__).parents[1] / "prompts").glob("*.md")}
    assert files == set(PROMPTS)


@pytest.mark.parametrize("name", sorted(PROMPTS))
def test_each_prompt_renders_with_no_placeholder_left(name):
    system, prompt = render(name, **PROMPTS[name])
    assert system
    assert "{{" not in prompt
    for value in PROMPTS[name].values():
        assert str(value) in prompt


def test_json_examples_keep_their_single_braces():
    _, prompt = render("score_market_news", **PROMPTS["score_market_news"])
    assert '"type": "market", "target": "INDIA"' in prompt
    assert prompt.count("{") == prompt.count("}")


def test_missing_and_unknown_values_fail_loudly():
    with pytest.raises(KeyError, match="needs values"):
        render("peers", name="x")
    with pytest.raises(KeyError, match="no placeholder"):
        render("peers", name="x", symbol="y", sector="z")


def test_version_defaults_to_one_and_is_read_from_front_matter(tmp_path, monkeypatch):
    import backend.prompts as prompts

    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "rule.md").write_text("Be plain.\n", encoding="utf-8")
    (tmp_path / "old.md").write_text("---\nsystem: One line: with a colon.\n---\nHi {{who}}", encoding="utf-8")
    (tmp_path / "new.md").write_text(
        "---\nversion: 3\nsystem: First line.\n  Second line.\n{{> rule}}\n---\nHi {{who}}\n{{> rule}}", encoding="utf-8")
    monkeypatch.setattr(prompts, "_DIR", tmp_path)
    prompts._load.cache_clear()
    try:
        assert prompts.prompt_id("old") == "old@1"
        assert prompts.render("old", who="a")[0] == "One line: with a colon."
        assert prompts.prompt_id("new") == "new@3"
        system, body = prompts.render("new", who="a")
        assert system == "First line.\nSecond line.\nBe plain."
        assert body == "Hi a\nBe plain."
    finally:
        prompts._load.cache_clear()


def test_summaries_share_the_plain_figures_rule():
    for name in ("summary_activity", "summary_day", "summary_holding", "summary_habits", "summary_weekly"):
        assert 'never as "1234 rupees"' in render(name, **PROMPTS[name])[1]
        assert "rupees;" not in render(name, **PROMPTS[name])[1]


def test_research_note_stays_general_and_chat_view_limits_other_users():
    from backend.prompts import shared_text

    system, _ = render("research_report", **PROMPTS["research_report"])
    assert "no buy, sell or hold call" in system
    assert "Never tell this trader to buy" in shared_text("chat_view_user")
    assert "not advice from a SEBI-registered adviser" in shared_text("chat_view_owner")
