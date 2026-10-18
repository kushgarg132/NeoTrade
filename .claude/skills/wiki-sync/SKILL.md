---
name: wiki-sync
description: Bring NeoTrade's agent wiki (docs/wiki/) up to date with HEAD by re-checking only the pages whose covered code changed since their verified_at commit. Use before any whole-app scan, audit or bug hunt, and when the user says "sync the wiki" or "update the wiki".
---

# wiki-sync

Goal: every page in `docs/wiki/` matches HEAD, at the lowest token cost.

0. In a fresh agent worktree, first `git merge --ff-only main`: worktrees start from the pushed commit, so unpushed fixes on local `main` would otherwise be invisible and every page would look current.
1. Run `python3 docs/wiki/stale.py --orphans`. Exit 0 and no orphans: say "wiki current at <sha>" and stop.
2. For each stale page (in parallel when there are several, one agent per page, each in its own worktree):
   - Read the page, then `git diff <verified_at>..HEAD -- <each changed file>`. Read whole files only where the diff is not enough to judge.
   - Rewrite only the sections the diff affects. Re-verify every anchor you touch with grep. Keep the format in `docs/wiki/INDEX.md`'s pages.
   - Set `verified_at` to the short HEAD sha.
3. Orphans: add each orphan file to the page whose area fits (extend `covers:` and the Files table), or list it under a new page only if no area fits; add new pages to the INDEX table.
4. Run `python3 docs/wiki/stale.py` again; it must exit 0.
5. Commit only `docs/wiki/` as `docs(wiki): sync to <sha>` and push with the repo's usual rules (ask the deploy-mode question if this is the session's first push; a docs-only change needs no deploy).

Never edit code in this skill. If a diff shows a bug, list it in the reply with file:line instead of fixing it.
