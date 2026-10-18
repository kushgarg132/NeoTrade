"""Which wiki pages are behind the code.

Each page in docs/wiki/ names the code it covers (`covers:` globs) and the
commit it was last checked against (`verified_at:`). A page is stale when a
file it covers changed between that commit and HEAD.

    python3 docs/wiki/stale.py            # stale pages + their changed files
    python3 docs/wiki/stale.py --orphans  # also: code files no page covers

Exit code 1 when any page is stale, so a scan can branch on it.
"""
import fnmatch
import subprocess
import sys
from pathlib import Path

WIKI = Path(__file__).resolve().parent
ROOT = WIKI.parent.parent
CODE = ("backend/", "frontend/src/", "docker-compose.yml", ".github/")
SKIP = ("/tests/", "__pycache__", "/handbook/", ".test.")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def front_matter(path: Path) -> dict:
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "---":
        return {}
    meta = {}
    for line in lines[1:lines.index("---", 1)]:
        key, _, value = line.partition(":")
        value = value.split("#")[0].strip()
        if value.startswith("["):
            value = [v.strip() for v in value.strip("[]").split(",") if v.strip()]
        meta[key.strip()] = value
    return meta


def covered(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in globs)


def main() -> int:
    pages = {p: front_matter(p) for p in sorted(WIKI.glob("*.md")) if p.name != "INDEX.md"}
    stale = 0
    for page, meta in pages.items():
        globs, sha = meta.get("covers") or [], meta.get("verified_at")
        if not globs or not sha:
            print(f"{page.name}: missing covers/verified_at")
            stale += 1
            continue
        changed = [f for f in git("diff", "--name-only", f"{sha}..HEAD").split()
                   if covered(f, globs) and not any(x in f for x in SKIP)]
        if changed:
            stale += 1
            print(f"{page.name}: stale since {sha} ({len(changed)} file(s))")
            for f in changed:
                print(f"  {f}")
    if "--orphans" in sys.argv:
        everything = [g for m in pages.values() for g in m.get("covers") or []]
        orphans = [f for f in git("ls-files").split()
                   if f.startswith(CODE) and not any(s in f for s in SKIP) and not covered(f, everything)]
        if orphans:
            print(f"not covered by any page ({len(orphans)}):")
            for f in orphans:
                print(f"  {f}")
    if not stale:
        print(f"wiki current at {git('rev-parse', '--short', 'HEAD').strip()}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
