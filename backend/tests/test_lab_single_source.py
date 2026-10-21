import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"SLIPPAGE_BPS\s*=|slippage_bps\s*=\s*\d")


def test_no_simulator_defines_its_own_slippage():
    hits = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if rel[0] in ("lab", "tests") or rel[:2] == ("forecast", "research"):
            continue  # offline research tools set their own slippage for sensitivity runs
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if PATTERN.search(line):
                hits.append(f"{path.relative_to(BACKEND)}:{n}: {line.strip()}")
    assert not hits, hits
