# Rebalance Conviction Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `conviction` target rule weighted by the existing composite score, plus AI-preselected new names.

**Architecture:** `rebalance.target_weights` gains a start-weight branch for `conviction`, sharing the cap-clip loop. The router gates it on `verdicts_visible_to` and enriches candidates with score and preselect. The tab adds the option and pre-ticks names.

**Tech Stack:** Python/FastAPI, pytest, React.

**Spec:** `docs/superpowers/specs/2026-10-05-portfolio-rebalance-design.md` (Addendum, Conviction rule)

## Global Constraints
- Multipliers:
  - ADD holding or AI pick: `1 + score.final`.
  - HOLD, funds, ETFs, unscored names, watchlist names: `1`.
  - SELL: `0`.
- Use `score.final` exactly as stored. No new blend. `AI_CAP` and `RULE_FLOOR` stay untouched.
- Conviction only where `verdicts_visible_to(user)`. Otherwise 403 with detail `"Conviction targets are not available on this account"`.
- Preselect: the top 5 AI candidates by score. They must be open LONGTERM BUY suggestions, with `expires_at > now`, and not held.
- Suite: `python3 -m pytest -q -p no:cacheprovider backend/tests`. Frontend: `npm run build`.

## Review Focus
1. Every free name is SELL (all multipliers 0): weight stays cash, with no ZeroDivisionError. Test in Task 1.
2. A SELL name must never receive redistributed weight from a cap clip. Test in Task 1.
3. A score dict missing or `None` on an ADD row: multiplier 1, no crash. Test in Task 1.
4. A suggestion with no `expires_at`: treated as open, not dropped by a None comparison. Test in Task 2.
5. Untick everything under Conviction: Calculate works with no candidates. This is UI, checked in the browser in Task 3.

### Task 1: Conviction weights (`backend/portfolio/rebalance.py`, `backend/tests/test_rebalance.py`)

**Produces:**
- `universe()` names also carry `verdict` and `score` (`row["score"]["final"]` or None).
- `plan_rebalance` candidates may carry `source` and `score`.
- `multiplier(name: dict) -> float`.
- `target_weights` handles `rule == "conviction"`.

- [ ] **Tests:**
  - `test_conviction_add_outweighs_hold_by_score`: ADD 0.8 vs HOLD gives weights in ratio 1.8 : 1.
  - `test_conviction_sell_gets_zero_and_never_absorbs`: SELL gets 0 even when a cap clips another name.
  - `test_conviction_all_sell_is_cash`: every name SELL gives the sum of weights == 0.
  - `test_conviction_ai_pick_weighted_watchlist_neutral`: an AI candidate scored 0.5 gets 1.5×; a watchlist candidate gets 1×.
  - `test_conviction_missing_score_is_neutral`: ADD with `score=None` gets 1×.
  - `test_conviction_caps_and_overrides_still_apply`.
- [ ] Run them and watch them fail. Implement: the start weight for free names is `rest × m / Σm` (all free names to 0 when `Σm == 0`). SELL names are pre-marked clipped. Then run the shared cap-clip loop. Run them and watch them pass.
- [ ] Commit: `feat(portfolio): conviction-weighted rebalance targets`

### Task 2: Gate, candidates, row actions (`backend/routers/portfolio.py`, `backend/tests/test_portfolio_rebalance_router.py`)

**Produces:**
- `_candidate_symbols` returns `[(symbol, source, score)]`.
- `/candidates` items gain `score` and `preselect`.
- POST passes `source` and `score` into candidates.
- 403 gate on POST.
- `with_suggestions` already passes rows with verdicts and scores to `target_gaps`.

- [ ] **Tests:**
  - `test_conviction_forbidden_when_verdicts_hidden`: a non-admin sending `targets.rule=conviction` gets 403, and so does a saved `conviction` rule.
  - `test_candidates_scored_sorted_top5_preselected`: 7 AI picks give score-descending order, `preselect` true on exactly the first 5, and watchlist items `score None, preselect False`.
  - `test_candidates_drop_expired_and_keep_no_expiry`.
  - `test_row_action_follows_saved_conviction_rule`: an admin with a saved conviction rule, where the ADD row's buy quantity equals its conviction gap.
- [ ] Run them and watch them fail. Implement. Run the full suite and watch it pass.
- [ ] Commit: `feat(portfolio): conviction rule gate and AI-preselected candidates`

### Task 3: Tab (`frontend/src/components/portfolio/Rebalance.jsx`)

- [ ] Add a third rule option **Conviction**, shown only when `snapshot.verdicts_visible`. Choosing it, or loading a saved conviction rule, sets `ticked` to the preselected symbols. AI pick badges show `AI pick · 0.72`. The caps fields show under both Caps and Conviction. Copy: "Conviction weights each stock by its review score: ADD gets more, SELL is sold. New names are the AI's top picks."
- [ ] `npm run build`.
- [ ] Commit, push with `[skip ci]` on HEAD, and deploy the backend in `/home/ubuntu/deploys/NeoTrade`.
- [ ] Browser check: Rebalance, then Conviction, then pre-ticked names, then Calculate gives 200, then a screenshot.
