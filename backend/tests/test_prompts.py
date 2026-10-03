"""Every LLM prompt lives in backend/prompts/*.md. Each must load, and
rendering must fail loudly on a missing or unknown placeholder."""

from pathlib import Path

import pytest

from backend.prompts import render

PROMPTS = {
    "resolve_instrument": {"query": "tata motors", "candidates": '[{"tradingsymbol": "TATAMOTORS"}]'},
    "peers": {"name": "Reliance Industries", "symbol": "RELIANCE"},
    "classify_events": {"text": "Q1 profit fell 23%"},
    "article_sentiment": {"target": "SBIN", "relevance_target": "SBIN", "headline": "h", "content": "c"},
    "score_news": {"symbol": "SBIN", "articles": "[0] headline"},
    "research_report": {"symbol": "SBIN", "sentiment_score": "-0.20", "relevant_count": 3, "news": "n", "events": "[]"},
    "index_move": {"name": "NIFTY 50", "session_date": "2026-09-26", "session": "- Close 25,123.45",
                   "trend": "- Month +1.2%", "peers": "- SENSEX: -0.40%", "movers": "- HDFCBANK: -1.90%",
                   "headlines": "- RBI holds rates (ET)"},
    "portfolio_review": {"totals": "Value 10,00,000.00", "concentration": "Largest HDFCBANK at 28%",
                         "holdings": "- HDFCBANK (STOCK): reason codes: overweight",
                         "candidates": "- TCS: score 0.62, reasons quality_momentum"},
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
    _, prompt = render("article_sentiment", **PROMPTS["article_sentiment"])
    assert '"is_relevant": true' in prompt
    assert prompt.count("{") == prompt.count("}")


def test_missing_and_unknown_values_fail_loudly():
    with pytest.raises(KeyError, match="needs values"):
        render("peers", name="x")
    with pytest.raises(KeyError, match="no placeholder"):
        render("peers", name="x", symbol="y", sector="z")
