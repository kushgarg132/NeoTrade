"""The replay's comparison: both columns read the same items, and only directions the report counts."""

from backend.datalayer.prompt_eval import compare


def _cell(cells, group, measure="move_5d"):
    return next(c for c in cells if c["group"] == group and c["measure"] == measure)


def test_compare_reads_only_items_the_new_prompt_scored():
    rows = [
        {"direction": 0.8, "new_direction": 0.8, "new_priced_in": 0.1, "move_5d": 0.02},   # both right, fresh
        {"direction": 0.8, "new_direction": 0.1, "new_priced_in": 0.9, "move_5d": -0.02},  # new too weak to count
        {"direction": -0.6, "new_direction": 0.7, "new_priced_in": 0.8, "move_5d": 0.01},  # stored wrong, new right
        {"direction": 0.9, "move_5d": 0.05},                                               # not replayed: left out
    ]
    cells = compare(rows)
    assert _cell(cells, "stored score") == {"group": "stored score", "measure": "move_5d", "n": 3, "hit": 1 / 3}
    assert _cell(cells, "new prompt")["n"] == 2 and _cell(cells, "new prompt")["hit"] == 1.0
    assert _cell(cells, "new, fresh")["n"] == 1
    assert _cell(cells, "new, priced in")["n"] == 1
    assert _cell(cells, "stored score", "pre_move_5d") == {"group": "stored score", "measure": "pre_move_5d", "n": 0, "hit": None}
