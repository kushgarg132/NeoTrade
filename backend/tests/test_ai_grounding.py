import pytest

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


def test_dates_and_times_in_facts_are_not_data():
    facts = ["Tue 06 Oct 2026 08:46 IST", "- 14:30 US CPI"]
    assert grounding.unsupported("Volatility may rise 30% after CPI; TCS could move 46%.", facts) == ["30%", "46%"]


# Real summaries the app stored (amounts changed), which broke the prompts' own rules.
@pytest.mark.parametrize("text,found", [
    ("Consequently, the day ended with an ai_net_pnl of 0.0 and ai_charges of 0.0.", ["ai_net_pnl", "ai_charges"]),
    ("ETERNAL results tomorrow may move your 1000.5 rupee position significantly.", ["1000.5 rupee"]),
    ("ADANIPOWER results will affect a 2.36% position worth 9,500.25 rupees; watch it.", ["9,500.25 rupees"]),
    ("The rupee fell and crude rose, so oil marketers lagged.", []),
    ("Your account is up ₹3,402 today; BAJAJ-AUTO and M&M led.", []),
])
def test_banned_finds_field_names_and_rupee_amounts_only(text, found):
    assert grounding.banned(text) == found


def test_a_banned_token_can_be_stripped_with_its_sentence():
    text = "Two orders filled. The net was ai_net_pnl of 0.0. Nothing else happened."
    assert grounding.strip_unsupported(text, grounding.banned(text)) == "Two orders filled. Nothing else happened."
