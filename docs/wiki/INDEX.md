# NeoTrade agent wiki

Dense, code-anchored pages for agents. Read these instead of scanning the repo.
Each page's front matter says which code it `covers` and the commit it was
`verified_at`. The handbook (`frontend/src/handbook/`) stays the human, in-app doc.

## Before you trust a page

```bash
python3 docs/wiki/stale.py            # exit 0: every page matches HEAD
python3 docs/wiki/stale.py --orphans  # also lists code no page covers
```

- **Page current** (not listed): trust it; open only the files you are about to change.
- **Page stale**: read the page, then only the changed files it lists (`git diff <verified_at>..HEAD -- <file>`).
  Before a whole-app scan, run the `wiki-sync` skill first so the pages are current.

## Pages

| Page | Area |
|---|---|
| [trading-engine](trading-engine.md) | Engine (backtest/paper/live), strategies, risk gates, kill switch, autopilot and fence, brokers, options, instruments |
| [mine-portfolio-journal](mine-portfolio-journal.md) | The trader's own account: holdings, lots, tax, XIRR curve, Needs you, Today, journal, guardrails, Telegram bot |
| [picks-and-signals](picks-and-signals.md) | Picks (setups, event study, calibration), factor model, composite score, suggestions, learning, builder |
| [data-ai-jobs](data-ai-jobs.md) | Ingest worker and data layer, LLM tiers and call sites, chat, game plan, research, prompts; every background job and its schedule |
| [platform](platform.md) | Auth, settings and prefs, WebSocket, system pages, every API endpoint, deploy, env var names |
| [frontend](frontend.md) | Routes, nav, page to endpoint to field map, shared components, session handling, build checks |

## Keeping it true

- A page is only as good as its anchors: every claim cites `path::symbol` or `path:line`.
- When you change code in a page's area, update that page in the same commit and set `verified_at` to the commit you checked against.
- Never put secrets or env values in a page; env var names only.
