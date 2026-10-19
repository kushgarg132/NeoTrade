"""python -m backend.lab rerun <run_id>

Rebuilds a stored `factor` or `study` run's inputs from its config, re-runs it and
compares the data fingerprint and every metric. Exit 0 same, 1 differs, 2 kind not
re-runnable here (engine/ml/bandit runs need data this command does not rebuild).
"""

import argparse
import asyncio
import json
import math
import sys
from datetime import date, datetime, timezone

import pandas as pd

from backend.lab.runs import LabRunStore, fingerprint

TOLERANCE = 1e-6
RERUNNABLE = ("factor", "study")


def _flat(x, prefix="") -> dict:
    if isinstance(x, dict):
        return {k: v for key, val in x.items() for k, v in _flat(val, f"{prefix}{key}.").items()}
    if isinstance(x, (list, tuple)):
        return {k: v for i, val in enumerate(x) for k, v in _flat(val, f"{prefix}{i}.").items()}
    return {prefix.rstrip("."): x}


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _deltas(then: dict, now: dict) -> dict:
    """Metric path -> {then, now} for every leaf that differs beyond TOLERANCE."""
    a, b = _flat(then), _flat(now)
    out = {}
    for k in a.keys() | b.keys():
        x, y = a.get(k), b.get(k)
        if _is_num(x) and _is_num(y):
            if x == y or (math.isnan(x) and math.isnan(y)) or abs(x - y) <= TOLERANCE:
                continue
        elif x == y:
            continue
        out[k] = {"then": x, "now": y}
    return out


def _plain(x):
    return json.loads(json.dumps(x, default=str))  # what Mongo stored: plain JSON types


def _cut(x, end: date):
    """Drop rows after `end` so a re-run sees only the data the run saw."""
    return x.loc[: pd.Timestamp(end)] if hasattr(x, "loc") else x


async def _factor(run: dict, sources: dict) -> tuple[str | None, dict]:
    from backend.factor import report
    from backend.factor.data import MARKET

    end = date.fromisoformat(run["window"][1])
    closes = _cut(sources["closes"](), end)
    series = sources["series"]
    out = await asyncio.to_thread(
        report.run, run["config"].get("start") or "2009-06-01", closes.index[-1],
        closes, _cut(series(MARKET), end), lambda t: _cut(series(t), end))
    return out["lab"]["fingerprint"], {"oos": out["oos"], "dsr": out["dsr"], "verdict": out["verdict"]}


async def _study(db, run: dict, sources: dict) -> tuple[str | None, dict]:
    from backend.forecast import picks, setups, study

    end = date.fromisoformat(run["window"][1])
    loader = sources.get("table")
    t = await loader() if loader else await picks.load(db, datetime.now(timezone.utc))
    if t is None:
        return None, {}
    t = {k: _cut(v, end) for k, v in t.items()}
    results, _ = await asyncio.to_thread(study.run, t, setups.SETUPS)
    return fingerprint(t["close"]), results.get(run["name"], {})


async def rerun(db, run_id: str, sources: dict | None = None) -> tuple[int, dict]:
    """sources (all optional, for tests): closes() -> DataFrame and series(ticker) -> Series
    (factor); async table() -> wide table (study)."""
    run = await LabRunStore(db).get(run_id)
    if run is None:
        return 2, {"error": f"no run {run_id}"}
    if run["kind"] not in RERUNNABLE:
        return 2, {"error": f"{run['kind']} runs are not re-runnable here"}
    sources = sources or {}
    if run["kind"] == "factor":
        from backend.factor import data
        sources = {"closes": lambda: data.closes(data.universe()), "series": data.series, **sources}
        fp, metrics = await _factor(run, sources)
    else:
        fp, metrics = await _study(db, run, sources)
    deltas = _deltas(run["metrics"], _plain(metrics))
    same = fp == run.get("fingerprint") and not deltas
    return (0 if same else 1), {"kind": run["kind"], "name": run["name"], "fingerprint_then": run.get("fingerprint"),
                                "fingerprint_now": fp, "deltas": deltas}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.lab")
    parser.add_argument("command", choices=["rerun"])
    parser.add_argument("run_id")
    args = parser.parse_args(argv)

    async def go():
        from backend.database import db
        await db.connect_to_database()
        return await rerun(db.db, args.run_id)

    code, report = asyncio.run(go())
    print(json.dumps(report, indent=1, default=str))
    print({0: "MATCH", 1: "DIFFERS", 2: "not re-runnable here"}[code])
    return code


if __name__ == "__main__":
    sys.exit(main())
