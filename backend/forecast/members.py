"""Point-in-time index membership for the Picks study, so it is not run on
today's survivors only (plan Phase 3). Each day's universe is the latest
NSE constituent list published on or before it: Nifty 200 where an archived
list exists, the CNX/Nifty 100 before 2014 (no 200 list survives from then).
Lists come from Wayback Machine copies of NSE's own CSVs, symbols moved to
today's via NSE's symbolchange.csv; see `nifty_members.csv`.

Rebuild: python -m backend.forecast.members DIR SYMBOLCHANGE_CSV
(DIR holds <index>_<wayback timestamp>.csv files)."""

import csv
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

MEMBERS_FILE = Path(__file__).with_name("nifty_members.csv")
# Before the first archived Nifty 200 list only Nifty 100 lists exist.
PREFER = ("n200", "cnx200")
FALLBACK = ("cnx100",)


@lru_cache(maxsize=1)
def snapshots() -> tuple[tuple[date, frozenset], ...]:
    rows: dict[date, set] = {}
    with MEMBERS_FILE.open() as f:
        for row in csv.DictReader(f):
            rows.setdefault(date.fromisoformat(row["as_of"]), set()).add(row["symbol"])
    return tuple((d, frozenset(s)) for d, s in sorted(rows.items()))


def ever() -> set[str]:
    return set().union(*(s for _, s in snapshots()))


def mask(days: pd.DatetimeIndex, symbols) -> pd.DataFrame:
    """days x symbols, True where the symbol was in the index that day (latest list on or before it;
    days before the first list use the first)."""
    snaps = snapshots()
    out = pd.DataFrame(False, index=days, columns=list(symbols))
    starts = [pd.Timestamp(d) for d, _ in snaps]
    for i, (_, members) in enumerate(snaps):
        lo = starts[i] if i else days.min()
        hi = starts[i + 1] if i + 1 < len(snaps) else None
        rows = (days >= lo) & (days < hi) if hi is not None else days >= lo
        cols = [s for s in out.columns if s in members]
        out.loc[rows, cols] = True
    return out


def _renames(path: Path) -> dict[str, str]:
    """old -> today's symbol, chains followed (A -> B -> C gives A -> C)."""
    step = {}
    with path.open(encoding="latin-1") as f:
        for row in csv.reader(f):
            if len(row) >= 3 and row[1].strip() and row[1].strip() != "OLD SYMBOL":
                step[row[1].strip()] = row[2].strip()
    def final(s: str) -> str:
        seen = set()
        while s in step and s not in seen:
            seen.add(s)
            s = step[s]
        return s
    return {old: final(old) for old in step}


def _symbols(path: Path) -> set[str]:
    """The Symbol column of one NSE list (older files carry title lines above the header)."""
    lines = path.read_text(encoding="latin-1").splitlines()
    head = next((i for i, l in enumerate(lines) if "Symbol" in l), None)
    if head is None:
        return set()
    return {r["Symbol"].strip() for r in csv.DictReader(lines[head:])
            if r.get("Symbol") and r.get("Series", "EQ").strip() in ("EQ", "")}


def build(folder: Path, changes: Path) -> list[tuple[date, str]]:
    """(as_of, symbol) rows: every Nifty 200 list, plus Nifty 100 lists dated before the first 200 list.
    One list per month (the latest)."""
    renames = _renames(changes)
    lists: dict[tuple[str, str], tuple[str, Path]] = {}
    for p in sorted(folder.glob("*_*.csv")):
        kind, ts = p.stem.rsplit("_", 1)
        kind = kind.rstrip("a")  # n200a: the same list from NSE's archive host
        if kind in PREFER + FALLBACK and len(_symbols(p)) >= 90:
            lists[(kind in PREFER and "200" or "100", ts[:6])] = (ts, p)
    first_200 = min((m for k, m in lists if k == "200"), default="999999")
    rows = []
    for (k, month), (ts, p) in sorted(lists.items()):
        if k == "100" and month >= first_200:
            continue
        as_of = datetime.strptime(ts[:8], "%Y%m%d").date()
        rows += [(as_of, renames.get(s, s)) for s in sorted(_symbols(p))]
    return rows


if __name__ == "__main__":
    out = build(Path(sys.argv[1]), Path(sys.argv[2]))
    with MEMBERS_FILE.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["as_of", "symbol"])
        w.writerows((d.isoformat(), s) for d, s in out)
    print(f"{len(out)} rows, {len({d for d, _ in out})} lists, {len({s for _, s in out})} symbols")
