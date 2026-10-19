# Picks: per-stock forecast from similar past setups (design)

Date: 2026-10-19. Status: approach approved in chat (option A), awaiting spec review.

## Why

Every pick of a setup shows the same numbers today (the setup's historical median, range and
P(up)), so APARINDS and LODHA both read "+1.1% median, 56% up". The owner wants a forecast per
stock. The LightGBM model failed its bar today (2026-10-19), so no ML: a conditional base rate
from the most similar past events of the same setup.

## Design

### `backend/forecast/similar.py` (pure)

- `features(t, symbol, p) -> np.ndarray | None` at signal day index `p`, bars up to `p` only:
  `vol60` (60-day daily return std), `mom` (12-1 month return), `dist_high` (close / 252-day
  high − 1), `strength` (the setup's signal value that day), `regime` (NIFTY close / its
  200-day mean − 1), `rel20` (stock 20-day return − NIFTY 20-day return). None when any is missing.
- `event_features(t, ev) -> pd.DataFrame`: features for every row of `study.events` (columns
  above + the event's `signal`, `exit`, `net`, `nifty`).
- `forecast(pool: pd.DataFrame, x: np.ndarray, k: int = K) -> dict`: z-score features with the
  pool's own mean/std, take the `k` nearest pool events by Euclidean distance, return
  `{n: k, median, p10, p90 (of excess = net − nifty), p_beat_nifty, p_up}`. `K = 150`,
  `MIN_POOL = 300` (fewer → None).
- Only events whose `exit` is before the forecast day enter the pool (no look-ahead).

### Validation (decides whether a setup uses it)

`validate(t, setup, ev) -> dict` per setup, yearly walk-forward (`lab/splits.yearly_folds`,
`min_train_years=3`; pool = events with `exit < test_start`): for each test event, the similar
forecast vs the plain setup base rate (pool's overall stats). Outputs `brier_similar`,
`brier_base`, `skill = 1 − brier_similar / brier_base` (on P(beat NIFTY)), and the rank IC of
forecast median excess vs realised excess. A setup is **personalised** when `skill > 0` and IC > 0
in at least 70% of test years; otherwise its picks keep the setup average, labelled
"setup average".

Stored with the study (`picks_study.setups[].similar = {skill, ic_years, personalised}`) and as a
`lab_runs` row (kind `study`, name `similar:<setup>`).

### Picks

- `forecast/picks.py::compute`: for each pick of a personalised setup, `expected`, `p_up`,
  `p_beat_nifty`, `median_excess` come from `similar.forecast`; add `forecast: "similar" |
  "setup"` and `similar_n`. Ranking (`rank_key`) uses the per-stock `median_excess ×
  p_beat_nifty`, so better-looking stocks rise.
- Forward record unchanged (the `predicted` fields now carry the per-stock values, so calibration
  of the new forecasts is measured from tomorrow).

### UI

- Ideas list row: median **excess vs NIFTY** (not absolute) and chance to beat NIFTY.
- Idea detail: "Based on 150 similar past <setup> setups" (or "Setup average — similar-setup
  forecast didn't beat it in testing"); range bar of excess; the 6 feature values for this stock
  in plain words (e.g. "near its 52-week high", "calmer than usual").

## Testing

- No look-ahead: features at p unchanged when later bars change; pool excludes events exiting on
  or after the forecast day.
- Planted data: excess depends on `dist_high` → personalised forecasts separate high/low, skill > 0,
  `personalised` True; noise → False and picks fall back.
- `forecast` returns None below `MIN_POOL`; z-scoring uses the pool only.
- Picks: two stocks of one setup get different expectations when personalised; identical when not.
- Runtime: full study + validation on the production table < 5 min on one core (vectorised
  distances; measure and record).

## Out of scope

ML models, new data sources (fundamentals), changing setups or horizons, live trading rules.
