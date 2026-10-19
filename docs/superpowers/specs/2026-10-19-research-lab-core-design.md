# Research Lab core (Phase 21 step 3): design

Date: 2026-10-19. Status: approved in chat, awaiting spec review.
Source: `docs/ROADMAP.md` Phase 21 step 3; plan doc "NeoTrade redesign: Picks you can trust"
(Reuse table: empyrical-reloaded for metrics).

## Goal

Every research number in NeoTrade comes from the same execution assumptions, the same
walk-forward method and the same metrics, and every run can be reproduced from what is stored.
Decided 2026-10-19: a shared core (`backend/lab/`) that the three existing simulators must use;
the simulators keep their own loop shapes (bar-by-bar, daily portfolio, event study).

## Today (what diverges)

| Simulator | Used by | Fills | Slippage | Walk-forward | Metrics |
|---|---|---|---|---|---|
| `engine/backtest.py::run_backtest` (over `engine/runner.py::run`) | backtest gate, retune, builder | next bar open | `BACKTEST_SLIPPAGE_BPS` 10 | none (retune DSR, builder trials) | `engine/metrics.py` per fill |
| `factor/backtest.py::simulate` | factor report, factor paper book | next close | `SLIPPAGE_BPS` 10 | `factor/validate.py::walk_forward` (yearly, no purge) | `factor/backtest.py::performance` |
| `forecast/study.py` | Picks, ML and bandit tools | t+1 to horizon | none | `study.walk_forward` (yearly, matured-before) | `study.stats` |

All three already charge `engine/execution/costs.py::calculate_indian_costs`; that schedule stays
the single source of charges.

## Design

### `backend/lab/assumptions.py`

- `@dataclass(frozen=True) class Execution: slippage_bps: float = 10.0; fill: Literal["next_open", "next_close"] = "next_open"`.
- `DEFAULT = Execution()`; `DAILY = Execution(fill="next_close")`.
- `fill_price(price: float, side: Side, ex: Execution) -> float`: adverse slippage (buy up, sell down).
- `round_trip_return(entry: float, exit_: float, ex: Execution, notional: float = 1e5, product: str = "CNC") -> float`:
  slipped entry and exit, charges on both legs, net return on notional.
- The engine's `SimulatedExecutionClient` (backtest), `factor/backtest.py::_trade` and
  `forecast/study.py::net_return` take their slippage and fill rule from an `Execution`.
  `BACKTEST_SLIPPAGE_BPS` and `factor/backtest.py::SLIPPAGE_BPS` are removed.
- A test (`test_lab_single_source.py`) fails if `SLIPPAGE_BPS` or a `slippage_bps=` literal
  other than through `Execution` appears outside `backend/lab/`.
- Effect: Picks study returns now include slippage (about 0.2% per round trip worse). Picks
  history already stored is not rewritten; the next 16:00 pass computes with slippage. The
  handbook and the Picks page caveats say so.

### `backend/lab/splits.py`

- `@dataclass(frozen=True) class Fold: year: int; train: tuple[date, date]; test: tuple[date, date]`.
- `yearly_folds(dates: Sequence[date], train_years: int, purge_days: int, embargo_days: int = 0) -> list[Fold]`:
  test = each calendar year after the first `train_years`; train = all dates before the test
  start minus the last `purge_days` trading days (removes labels that overlap the test year);
  `embargo_days` trading days after a test year are dropped from later trains.
- Users: `factor/validate.py::walk_forward` (rolling 3-year window, purge 0, as today) and
  `forecast/study.py::walk_forward` (expanding, keeps its `exit < test_start` event purge).
  Retune and builder keep their single hold-out split; the research tools are unchanged
  (planning ruling: both would change outcomes or cannot run in prod/tests).
- Current outputs must not change where purge/embargo are 0 (tests pin that).

### `backend/lab/metrics.py`

- `summary(daily_returns: pd.Series, benchmark: pd.Series | None = None) -> dict` with keys
  `cagr, sharpe, sortino, max_drawdown, volatility, alpha, beta` (alpha/beta None without a
  benchmark), via `empyrical` from `empyrical-reloaded==0.7.0` (Apache-2.0, pure Python + numpy/scipy;
  verified importing in the prod image 2026-10-19).
- `factor/backtest.py::performance` and `study.stats` keep their own fields and add `summary`.
- The backtest gate's metrics (`engine/metrics.py`, thresholds in `risk/backtest_gate.py`) are
  unchanged in this step; the gate result additionally stores `summary` for comparison.

### `backend/lab/runs.py`

- Collection `lab_runs`: `_id` uuid, `kind` (`engine`|`factor`|`study`|`ml`|`bandit`), `name`
  (strategy, setup or variant), `config` (dict: params, universe, horizon), `execution`
  (`Execution` as dict), `window` (`start`, `end`), `fingerprint` (sha256 of the input bar table:
  sorted symbols, dates and close values, rounded to 4 dp), `code_sha` (`GIT_SHA` env, else
  `git rev-parse HEAD`, else `"unknown"`), `folds` (list of Fold dicts, may be empty), `metrics`
  (`summary` plus kind-specific fields), `user_id` (who started it; system runs use `"system"`),
  `created_at`. Index `(kind, name, created_at)`.
- `LabRunStore.record(...) -> str`, `get(id)`, `list(kind=None, name=None, limit=50)`.
- `fingerprint(frame: pd.DataFrame) -> str` in the same module.
- Writers: `risk/gate_backtest.py::backtest_for_gate`, `factor/report.py::run`,
  `forecast/picks.py::run` (the study it runs), `learning/retune.py::retune_strategy`,
  `builder/draft.py::test_one`, both research tools. A failure to record logs a warning and never
  fails the run.
- `python -m backend.lab rerun <id>`: loads the run, rebuilds inputs for its kind and window,
  recomputes, prints both fingerprints and metric deltas, exit 1 when the fingerprint differs
  (data changed) or a metric differs by more than 1e-6 with the same fingerprint (code changed).
  `kind` dispatch covers `factor` and `study` in this step; `engine` (needs broker history) and
  `ml`/`bandit` (need lightgbm, not in prod) print "not re-runnable here" and exit 2.

### API and UI

- `GET /lab/runs?kind=&name=&limit=` and `GET /lab/runs/{id}`, admin only (`require_admin`),
  in a new `backend/routers/lab.py`.
- Lab gets a "Runs" tab (`/lab/runs`, admin): newest first, kind, name, window, code SHA,
  CAGR/Sharpe/max DD. Selecting two runs shows their metrics side by side; no charts in this step.

## Error handling

- `summary` on fewer than 2 returns returns all keys None.
- `yearly_folds` with fewer years than `train_years + 1` returns `[]`; callers treat that as
  "not enough history" as they do today.
- `record` never raises into the simulator.

## Testing

- Parity: one BUY at 100, SELL at 110, CNC, `DEFAULT` gives the same net return through
  `round_trip_return`, the engine backtest client and `factor/backtest.py::_trade` (one stock,
  full weight).
- Folds: purge removes exactly `purge_days` trading days before each test year; embargo removes
  the days after; purge 0 reproduces today's factor walk-forward result on a fixture.
- Metrics: `summary` matches empyrical on a seeded series; benchmark None gives alpha/beta None.
- Runs: record then `get` round-trips; `fingerprint` is order-independent over symbols and
  changes when one close changes; `rerun` on a stored factor run with a fixture data source
  exits 0.
- Existing gate, factor, Picks and study tests stay green (updated only where slippage now
  applies to study returns).
- Gate: in-image pytest, import-linter (add contract: `backend.lab` imports no `backend.routers`,
  no `backend.autopilot`), frontend node tests + build.

## Docs

`docs/wiki/picks-and-signals.md`, `trading-engine.md`, `platform.md` (endpoints), frontend page
map; handbook page for the Lab; `PRODUCT.md` Lab surface; `docs/ROADMAP.md` step 3 status.

## Out of scope

Indicator dedupe (talipp/TA-Lib), changing gate metrics or thresholds, charts in the Runs view,
re-running engine runs from stored data (needs a stored bar cache), new strategies.
