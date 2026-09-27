from backend.options.resolver import FO_UNDERLYINGS, is_fo_eligible


def test_is_fo_eligible():
    assert is_fo_eligible("RELIANCE")
    assert not is_fo_eligible("SOMESMALLCAP")
    assert len(FO_UNDERLYINGS) == len(set(FO_UNDERLYINGS))
