from backend.ai import grounding

FACTS = [{"as_of": "2026-10-06T04:00:00+00:00", "symbol": "TCS", "last_close": 2114.39, "ret_20d": 2.347,
          "items": [{"impacts": [{"impact": 7, "direction": -0.6}]}], "pe": "28.4"}]


def test_fabricated_price_is_caught():
    assert grounding.unsupported("TCS closed at ₹2,500 today.", FACTS) == ["₹2,500"]


def test_rounding_and_percent_precision_pass():
    text = "TCS last closed at ₹2,114.4, up 2.3% over 20 days, PE 28.4, news impact 7/10."
    assert grounding.unsupported(text, FACTS) == []


def test_dates_times_years_are_ignored():
    text = "On 2026-10-06 at 09:15 IST, in 2026, on 06 Oct, TCS held ₹2,114.39."
    assert grounding.unsupported(text, FACTS) == []


def test_small_bare_numbers_and_list_markers_are_ignored():
    assert grounding.unsupported("1. Watch TCS.\n2. Hold 3 names.", FACTS) == []


async def test_retry_then_strip():
    calls = []

    async def retry(tokens):
        calls.append(tokens)
        return "TCS rose 2.3% this month. It may test ₹3,000 soon."
    text, ok = await grounding.grounded("TCS rose 9% this month. It may test ₹3,000 soon.", FACTS, retry)
    assert calls == [["9%", "₹3,000"]]
    assert text == "TCS rose 2.3% this month." and ok is False


async def test_grounded_text_passes_untouched():
    text, ok = await grounding.grounded("TCS last closed at ₹2,114.39.", FACTS, None)
    assert ok is True and text == "TCS last closed at ₹2,114.39."


def test_strip_keeps_lines_and_list_structure():
    text = "Summary:\n1. RELIANCE rose 9.9%.\n2. TCS last closed at ₹2,114.39.\n\nOverall fine."
    out = grounding.strip_unsupported(text, ["9.9%"])
    assert out == "Summary:\n2. TCS last closed at ₹2,114.39.\n\nOverall fine."


def test_token_match_is_exact_not_substring():
    assert grounding.strip_unsupported("Up 12.3% today. Down 2.3% later.", ["2.3%"]) == "Up 12.3% today."


def test_percent_tolerance_is_half_a_unit_of_the_last_digit():
    facts = [{"x": 2.9}]
    assert grounding.unsupported("rose 2%", facts) == ["2%"]
    assert grounding.unsupported("rose 3%", facts) == []


def test_dollar_and_rs_amounts_are_figures():
    assert grounding.unsupported("Crude at $150; stock at Rs. 450.", [{"x": 1.0}]) == ["$150", "Rs. 450"]
