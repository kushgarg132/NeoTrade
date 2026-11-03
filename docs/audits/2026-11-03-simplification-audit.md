# Simplification audit, 2026-11-03

Scope: whole repo at `b6c918d`. No code changed. Every batch below waits for owner approval.

**Result:** about 3,200 production lines can go (about 5% of 62,110) if decision D1 is approved, or about
1,450 without it. Another 690 test lines go with D1. The system-design batches (B5, B6) make the code
clearer but save about zero lines. The largest functions are mostly in the money and safety paths, so this
audit does not propose changing their behaviour.

## Baseline

| Check | Result |
|---|---|
| Backend tests | 2573 passed, in a throwaway offline read-only container from the deployed image |
| Frontend tests | 583 passed |
| Frontend build | Passes |
| `lint-imports` | **Fails** in the deployed container: `No matches for ignored import backend.engine.autorun -> backend.routers.trading.` No GitHub workflow runs it |
| `npm run lint` | **10 errors.** The 7 visible in the output are in the untracked `frontend/.harness/vite.config.js`; the other 3 were cut off |
| Wiki | `stale.py`: current at `b6c918d`, but see B1 for stale content it cannot detect |
| Size | Backend 41,733 lines, plus 39,060 of tests. Frontend JS and JSX 20,377 lines, excluding tests |

Tools: vulture, radon, pylint duplicate-code, and own AST and import-graph scripts. `knip` was refused by the
session's permission system (it downloads external code), so unused frontend code comes from the own scripts.

Scan output needing care:

- vulture flags about 110 FastAPI route handlers and pydantic validators. These are false positives.
- `engine/execution/autopilot.py:36` `yield` after `return` is deliberate: it makes an empty async generator.
- `lxml` looks unused but is needed: `BeautifulSoup(..., features="xml")` (`routers/news.py`, `datalayer/news_sources.py`).

## Batches, safest and largest payoff first

Net lines are estimates, except file sizes measured with `wc -l`.

### B1. Fix broken checks and stale text. Risk: low. Net: about -10

| Finding | Evidence | Change |
|---|---|---|
| Import contract check fails | `backend/.importlinter:50` ignores an import that no longer exists | Delete that line |
| Removed package still in contracts | `backend.plan` at `.importlinter:31,78,120,169`; `backend/plan/` holds only `__pycache__` | Delete the entries and the directory |
| Nothing enforces import contracts | No `lint-imports` in `.github/workflows/` | Add one CI step |
| Dead index | `server.py:178` indexes `paper_limit_orders`; nothing else uses it (`docs/wiki/trading-engine.md:254`) | Delete the line |
| Game plan text remains | `docs/wiki/data-ai-jobs.md:84,103`, `docs/wiki/platform.md:107`, `frontend/src/handbook/ai-and-news.md:46`, `learning/library.py:7` | Correct the text |
| Local lint noise | `frontend/.harness` is untracked but linted | Add to eslint ignores |

Verify: `lint-imports` passes, `npm run lint`, backend tests.

### B2. Delete unreachable frontend code. Risk: low. Net: -1,158, plus dead helpers

Not reachable from `main.jsx`; no `import.meta.glob` exists in `frontend/src`.

| File (under `frontend/src/`) | Lines |
|---|---|
| `components/suggestions/SuggestionRecord.jsx` | 344 |
| `components/decisions/WaitingCards.jsx` | 131 |
| `components/trading/TradingControlBar.jsx` | 120 |
| `components/mine/ValueCurve.jsx` | 112 |
| `components/mine/NeedsYou.jsx` (the live one is `components/home/NeedsYou.jsx`) | 104 |
| `components/analysis/SentimentPanel.jsx` | 85 |
| `components/mine/Mix.jsx` | 61 |
| `components/common/StopAutopilot.jsx` | 47 |
| `utils/practice.js` and its test | 34 |
| `components/common/AccountSwitch.jsx` | 33 |
| `components/common/Card.jsx` | 32 |
| `components/ui/Tile.jsx` | 27 |
| `components/mine/VerdictStamp.jsx` | 17 |
| `components/common/MoneyBadge.jsx` | 11 |

Also, exports nothing in production imports:

- No test: `clearRecentStocks`, `usePendingCount`.
- Test only: `TOOLTIP_STYLE`, `groupHoldingActions`, `olderPickLabel`, `sectorRows`, `targetProgress`,
  `hasRecentNews`, `sortByNewsRisk`, `amountParts`, `sectionsFor`. `ROUTES`, `ADMIN_ROUTES` and
  `PUBLIC_ROUTES` need a look first, because `routes.js` may use them internally or as a test contract.

Tests that read deleted files by path need editing: `common/leftovers.test.js` (StopAutopilot) and
`market/marketIdentity.test.js` (TradingControlBar). Do not weaken other assertions.
Update `docs/wiki/frontend.md` and the handbook's ValueCurve and NeedsYou mentions.

Verify: frontend tests and build.

### B3. Delete small dead backend code. Risk: low. Net: about -200

| Item | Lines | Evidence |
|---|---|---|
| `system/seed_backlog.py` and `test_seed_is_idempotent` | 147 + about 8 | Documented as one-time, and the backlog is live |
| `routers/trading.py:169` `get_active_broker_adapter` | 11 | No references |
| `strategies/indicators.py:203` `analyze_market_structure` | 8 | No references; a stub calling `detect_trend` |
| `instruments/indian_stocks.py:49` `get_stock_symbol_nse` | 3 | No references |
| `engine/execution/live_order_store.py:92` `update_status` | 10 + test | Tests only. Check `claim` covers all live writes first |

Verify: backend tests. `update_status` is in the live order store, so it gets its own commit.

### B4. One home for time helpers. Risk: low. Net: about -40

- `_aware` has 13 copies in two variants, one safe with `None`. Use one None-safe version.
- `_now` has 5 copies, `today_ist` has 2, and `IST` is defined twice (`engine/session.py:12`, `routers/settings.py:64`).
- Move them to one module, and keep the `test_no_datetime_now.py` rule intact.
- Skip `datalayer/filings.py` and `datalayer/news_sources.py` until the `doing` Filing lane item lands.

Verify: backend tests, including the clock grep test.

### B5. Routers stop being imported as libraries. Risk: medium, split by module. Net: about 0

Domain code imports from `routers/` at 20 sites, 14 of them listed as known debt in `.importlinter`. Moving
the helpers removes those ignores. Moves only, with no logic change. Tests that monkeypatch old paths need updating.

| Move out of | Helpers | Risk |
|---|---|---|
| `routers/news.py:32-63` | `_title_key`, `fresh_headlines`, `fetch_news_logic` | Low. Wait for the Filing lane if it touches them |
| `routers/portfolio.py:31-40` | `mask_row`, `present` | Low |
| `routers/market_data.py` | `_known_index_names`, `_quotes`, `get_trending_stocks`, index tables, Yahoo fetch and scan logic | Low |
| `routers/settings.py:503-650` | LLM usage: `fetch_usage`, `fetch_feature_usage`, `UsageUnavailable` | Low |
| `routers/suggestions.py:55` | `_live_mark_price` | Medium |
| `routers/trading.py:96-460` | Run launching: `launch_run`, `stop_background_run`, cancel handling | **High.** Contains gate selection, so needs D5 |
| `chat/actions.py:491,536` | Calls route handlers with a fake user | **High.** Approve path places real orders, so needs D5 |

### B6. Split `routers/settings.py` by domain. Risk: low to medium. Net: about 0

842 lines and 28 routes mix preferences, strategies (lines 189-416), LLM gateway (441-775) and broker
credentials (779-842). Split into 3 or 4 routers with identical URLs and auth dependencies. Do this after B5.

Verify: snapshot `app.openapi()` before and after. Paths, methods and models must match exactly.

### B7. One set of UI primitives. Risk: medium, visual. Net: about -60

`components/common/Button.jsx` and `Badge.jsx` have 4 importers each, against 30+ for the `ui/` versions.
Move those importers to `ui/` and delete the `common/` versions. Needs a visual check on a phone-sized viewport.

### B8. Break up the most complex read-only functions. Risk: medium. Net: about +0 to +30

Only with tests pinning current output first:

| Function | Complexity |
|---|---|
| `mine/actions.py:71` `build` | 57 |
| `journal/insights.py:130` `build_insights` | 57 |
| `mine/stock.py:45` `detail` | 56 |
| `portfolio/digest.py:66` `pulse` | 44 |
| `portfolio/rebalance.py:52` `target_weights` | 39 |

This helps a reader but saves no lines. Do one function per commit.

## Decisions needed from the owner

| # | Decision | Effect | Recommendation |
|---|---|---|---|
| D1 | Carry out audit item P2-1 (`docs/audits/2026-10-24-trading-edge-audit.md:463`): delete research tools (1,142), `ml/` (262), `rl/` (337), `lightgbm` | -1,741 production lines, -688 test lines, smaller image | **Yes**, findings kept in the roadmap and git. Caveat: `new_setups_tool` and `news_picks_tool` were used after that audit, on 2026-10-26 and 27. Keep them if more studies are planned. `factor/survivorship.py` stays, since it was used on 2026-11-03 |
| D2 | Remove direct dependencies with no importers: `langchain`, `langchain-google-genai` (which brings `google-genai`) | Smaller image | **Yes**, in its own commit with an image build. No lockfile exists, so versions may shift |
| D3 | Remove API routes no page calls: `/trading/equity` (returns unmarked equity), `/broker/list`, `/journal/ai-vs-me`. The wiki also lists `/news/market` and `/stock_info*`, not yet checked | Small | Remove the first three. Keep `/today/reconciliation` and `/system/reconciliation`: the handbook documents them. They do share a query that could be one helper |
| D4 | Unify duplicate gate-read metrics (`engine/metrics.py`, `analytics.py`) | About -60, but **re-grades strategies** | Not as part of this work. Decide separately |
| D5 | Allow moves in the trading run launcher and chat approve path | Clears the last router debt | Only after B5's low-risk moves. Moves only, one commit each |
| D6 | Refactor `engine/runner.py` `run` (complexity 65) and `size_intents` (64, 18+ parameters) | Clearer core | **Not now.** These are the money path and the golden parity test guards them. Needs its own spec |
| D7 | Remove old worktrees and branches: 20 worktrees, 38 branches, 513 MB | Disk, not code | Check each one first, since other sessions may own them |

## Not recommended

- Renaming `backend/data` and `backend/datalayer`. The names are confusing, but it causes wide churn for no behaviour gain.
- Sharing NSE holidays between `frontend/src/utils/formatters.js:95` and `core/market_calendar.py`. This is real duplication, but it needs a new API field. Add it when holidays next need updating.
- Trimming the 39,060 test lines broadly. Only tests of deleted code go.

## Not verified

- Dynamic uses of backend symbols beyond name grep. Backend tests are the backstop.
- Frontend reachability relies on a regex import scan, not a bundler graph. The build is the backstop.
- Image size saved by D1 and D2 was not measured.
- Line estimates for B4 to B8 were not validated by doing the work.
- Other sessions may be active (Filing lane is `doing`). Check `git log` before each batch.
