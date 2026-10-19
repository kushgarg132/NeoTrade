# Picks per-stock forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Each pick gets its own expected excess vs NIFTY and chance to beat NIFTY from its 150 most similar past events of the same setup, used only for setups where that beats the setup average in walk-forward testing.

**Architecture:** Pure `backend/forecast/similar.py` (features, forecast, validate); `forecast/picks.py::compute` uses it for personalised setups; study stores the validation; Ideas UI shows excess vs NIFTY and the "similar setups" explanation.

**Tech Stack:** Python 3.11 prod image, numpy/pandas; React 19 frontend (`node:test`).

**Spec:** `docs/superpowers/specs/2026-10-19-picks-per-stock-forecast-design.md`

## Global Constraints

- `K = 150`, `MIN_POOL = 300`; features `vol60, mom, dist_high, strength, regime, rel20` from bars up to the signal day only; z-score with the pool's own mean/std; Euclidean distance.
- Pool = same-setup events with `exit < forecast day` (forecast) or `exit < test_start` (validation).
- Personalised setup: `skill > 0` (Brier on P(beat NIFTY) vs pool base rate) AND rank IC > 0 in ≥ 70% of test years; folds `yearly_folds(min_train_years=3)`.
- Pick fields added: `forecast: "similar" | "setup"`, `similar_n`, `features` (dict of the 6 values); `expected`/`p_up`/`p_beat_nifty`/`median_excess` per stock when similar. `expected` holds EXCESS quantiles under key `excess: {median,p10,p90}` in addition to the existing absolute ones.
- Study adds per setup `similar: {skill, ic_years, personalised}`; a `lab_runs` row kind `study`, name `similar:<setup>` (best effort).
- Picks job must stay < 5 extra minutes on one core; measure on a synthetic full-size table.
- Backend gate in the prod image (`docker build -q -t neotrade-verify-pf backend && docker run --rm -w /app -v "$PWD/pytest.ini:/app/pytest.ini:ro" neotrade-verify-pf sh -c "python -m pytest -q backend/tests; lint-imports --config backend/.importlinter"`); frontend `node --test` + `npm run build`.
- STRICT: implementers never push, never merge, never touch the main checkout. Trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1 (backend): similar forecasts + validation + picks integration
**Files:** create `backend/forecast/similar.py`, `backend/tests/test_forecast_similar.py`; modify `backend/forecast/picks.py` (compute, study storage, `_record_runs`), `backend/tests/test_forecast_picks.py` (only where outputs change), wiki `picks-and-signals.md`.
- [ ] Failing tests: no look-ahead (features, pool), planted `dist_high` signal → personalised + different forecasts for two stocks, noise → not personalised and setup average kept, `forecast` None below MIN_POOL, runtime < 300 s on 236×17y synthetic.
- [ ] Implement, vectorise distances, suite green, commit `feat(picks): per-stock forecast from similar past setups`.

### Task 2 (frontend): show it
**Files:** `frontend/src/utils/ideas.js` (+test), `frontend/src/components/ideas/*`, `frontend/src/pages/IdeaDetail.jsx`.
- [ ] List row: median excess vs NIFTY (`expected.excess.median`, falling back to `median_excess`) + "beats NIFTY N%"; detail: "Based on {similar_n} similar past {label} setups" or "Setup average", excess range bar, the 6 features in plain words (`describeFeatures(features) -> string[]`, node test: e.g. dist_high > −0.03 → "near its 52-week high").
- [ ] node tests + build green, 390 px light/dark screenshots, commit `feat(fe): per-stock pick forecast on Ideas`.

Tasks 1 and 2 run in parallel (field names fixed above).

## Ship
- [ ] Merge both, gate, review, deploy direct (backend), push (Vercel); run `picks.run` once by hand to refresh today's picks; check two picks of one setup now differ (if personalised).
