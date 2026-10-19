import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.forward.scorecard import label, scorecard, stats


def rec(net, nifty, p=None):
    return {"outcome": {"net": net, "nifty": nifty, "excess": net - nifty, "won": net > 0},
            "predicted": {"p_up": p} if p is not None else None}


def test_rule_boundaries():
    base = {"mean_excess": 0.01, "t": 2.0, "calibration_gap": 0.05}
    assert label({**base, "n": 100})["label"] == "proven"
    assert label({**base, "n": 99})["label"] == "unproven"
    assert label({**base, "n": 100, "t": 1.99})["label"] == "unproven"
    assert label({**base, "n": 100, "calibration_gap": 0.051})["label"] == "unproven"
    assert label({**base, "n": 100, "calibration_gap": None})["label"] == "proven"
    assert label({**base, "n": 150})["progress"] == 100


def test_stats_with_and_without_predictions():
    s = stats([rec(0.02, 0.01, 0.6), rec(-0.01, 0.0, 0.6)])
    assert s["n"] == 2 and s["hit_rate"] == 0.5
    assert s["calibration_gap"] == pytest.approx(0.1)
    assert s["brier"] == pytest.approx((0.16 + 0.36) / 2)
    assert stats([rec(0.02, 0.01)])["brier"] is None
    assert stats([rec(0.02, 0.01)])["t"] is None


async def test_scorecard_news_gate_and_disagreement():
    db = AsyncMongoMockClient()["t"]
    await db["forward_records"].insert_many(
        [{"_id": str(i), "source": "news", "name": "x", **rec(0.01, 0.0)} for i in range(3)])
    await db["news_theme_weights"].insert_one({"_id": "x", "weight": 1.2, "n": 30})
    [row] = await scorecard(db)
    assert row["gate"] is True and row["label"] == "unproven" and row["disagrees"] is True
