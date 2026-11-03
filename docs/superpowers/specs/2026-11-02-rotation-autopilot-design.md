# Rotation autopilot: one evidence-checked engine and a daily plan

Date: 2026-11-02. Owner decisions (this session): absolute return, more active; ₹1–3L on paper
first; no passive core, 100% active; engine A (weekly relative-strength rotation); news must be
considered.

## Why

The autopilot had four entry sources, and none of them traded:
- Picks: no setup reaches grade A since 2026-10-27.
- Engine and news proposals: every strategy is parked or has no passed gate. 0 of 33 pass, and
  intraday loses before charges.
- The factor book: monthly, on its own ₹3L paper book, not the AI account.

The daily "game plan" was an LLM plan for the intraday auto-run. It was built only with the Lab
switch on, `auto_paper_intraday` on, and a broker logged in that morning. It also only steered
strategies that no longer trade. So the owner saw no plan and could not see why anything traded.

## What

**Engine** (`backend/factor/model.py::ROTATION`, traded by `backend/autopilot/rotation.py`):
- Universe: Nifty 200 (`factor/nifty200.csv`).
- Score: 0.4 z(3-month return / vol) + 0.4 z(6-month return / vol) + 0.2 z(close / 52-week high).
  Returns skip the latest week.
- Hold the top 8 at equal weight. A holding is kept while it ranks within 25.
- Rebalance weekly: decided on the last finished session's closes at the first morning pass
  (09:20 IST) of an ISO week, then stored in `rotation_targets`.
- Risk-off means all cash. That happens when the Nifty is under its 200-DMA.
- No per-name stop and no breadth filter. A 3×ATR trailing stop and a "40% above the 50-DMA"
  breadth rule were built and tested. Both cut net returns in every variant (see Evidence), so
  they stay only as backtest parameters (`Params.stop_atr`, `Params.breadth_min`).
- Sizing:
  - The book's capital is `max_exposure`, plus the rotation's closed net P&L and open marks,
    capped at `max_exposure`.
  - Each name is sized to weight × book, under `per_trade_cap`, in whole shares.
  - A name whose share price is above its slot is skipped.

**News** only ever removes:
- At the weekly decision and at every buy, a name is vetoed when its stock sentiment
  (`sentiment:{symbol}` in Redis) is ≤ -0.5, or when its results are due within 3 days
  (`mine.events.upcoming`).
- A held name with such a flag is shown in the plan. It is not sold on news: no history proves
  that helps.
- News-triggered entries (`datalayer/reactor.py` → `_autopilot_proposals`) are removed.

**Execution:** every order goes through `autopilot/service.submit`, so the fence, the kill
switch, the daily loss limit, the paper/live switch and the `ai`-role broker all still apply.
- Source is `rotation`, strategy `rotation`, CNC.
- The 15-minute long-term pass (from 09:20) trades the book toward the target: sells first, then
  buys. A refused buy retries at the next pass.
- With the autopilot off, only sells run.

**Daily plan** (`rotation.plan`, collection `rotation_plans`, `GET /plan/today`, Telegram
`money` alert at the morning pass, AI → Activity plan card). It contains:
- regime (Nifty vs 200-DMA, breadth);
- holdings with P&L, this week's rank, and any news flag;
- today's sells and buys, with the reason for each block;
- this week's news vetoes;
- the next 10 names on the watch list;
- the next rebalance date;
- whether it is paper or live.

It is built every trading day for every user with the autopilot on or rotation positions open.
It needs no broker login and no Lab switch. It is pure arithmetic: no LLM decides or writes it.

## Removed from the autopilot

- Picks entries (`autopilot/picks.py::enter`). Picks exits stay for open positions; Picks stays
  as admin research.
- Engine proposals and news proposals to the autopilot (`autorun._autopilot_proposals` and its
  reactor call).

## Evidence on point-in-time membership (2026-11-03): this replaces the figures below

`python -m backend.factor.survivorship rotation`: net of charges, 10 bps slippage, 2013-2026, ranking only that
day's Nifty 200 members (`forecast/members.py`). 2019-02 to 2023-08 rolls forward through NSE's press releases
and lands within 9 of 200 names on the real 2023-08 list.

| | CAGR | Sharpe | Max DD |
|---|---|---|---|
| Rotation, today's list (biased) | 29.5% | 1.42 | -36% |
| Rotation, point in time | 16.2% | 0.90 | -42% |
| Rotation, walk-forward, point in time | 13.3% | 0.81 | -34% |
| Equal weight of the same members, no costs | 15.0% | | |
| Nifty 200 price index, about 1.3% a year of dividends on top | 11.3% | | |

- Deflated Sharpe 0.974 (16 trials). Ahead of equal weight in 6 of 14 years.
- 2020 and 2021 hold the edge: +28 and +54 points over equal weight. 2018 lost 30% against -9%, on real names
  (VAKRANGEE, PCJEWELLER) and whipsaw, not bad prices. No one-day move over 25% while held.
- Since 2022-08: 16.3%, Momentum 30 ETF 8.3%, Nifty 200 8.7%.
- Remaining bias: 52 of 405 past members have no Yahoo prices. They are mostly names that left or failed, so the
  figures are still somewhat high.
- Not in the figures: tax.

## Earlier evidence (2026-11-02, `factor/backtest.py`, net of charges, 10 bps slippage, today's Nifty 200 list)

These are inflated by survivorship; see above.

Walk-forward over 8 variants (top 8/12 × stop on/off × breadth on/off), 3-year in-sample, out
of sample 2013-2026:

| | CAGR | Sharpe | Max DD |
|---|---|---|---|
| Rotation (walk-forward) | 22.5% | 1.20 | −37% |
| Nifty 200 index | 11.6% | 0.76 | −38% |

- The deflated Sharpe is 0.999 (16 trials counted).
- Full-period variants:
  - top 8, no stop or breadth: 26.5% CAGR, turnover 10× a year, cost drag 1.2%;
  - with the stop: 18.0% CAGR, turnover 25×, cost drag 3.0%;
  - with the stop and breadth: 13.5% CAGR.

**Bias-cancelled checks** (both sides carry the same survivorship bias):
- Against equal weight of the same 200 names, 2012-2026:
  - top 8: +2.5% a year (26.4% vs 23.9%), ahead in only 7 of 15 years;
  - top 12: −0.7% a year.
  - It wins big in trending years (2014, 2020, 2021, 2023: +30 to +50 points) and lags in choppy
    ones (2015, 2019, 2024, 2025: −13 to −22).
- Against a Momentum 30 replica on the same names, over the Momentum 30 ETF's life
  (2022-08 to 2026-11):
  - top 8 makes 27.2% vs the replica's 19.3%;
  - the real ETF made 8.3%, so the estimated real CAGR is 16.2%.

**Verdict:**
- A momentum tilt with a real but noisy edge over its own universe. The edge is about +2.5% a
  year over 14 years; about +8% a year over the last 4.
- The −37% drawdown is the price.
- No promise of profit. The forward paper record decides.

## Evidence gate before live money

1. Walk-forward with a deflated Sharpe ≥ 0.95. Met on point-in-time membership: 0.974.
2. Bias-neutral check: must beat the Momentum 30 ETF. Met on point-in-time membership: 16.3% vs 8.3% since 2022-08.
3. 3 months of forward paper results ahead of the Nifty. Until then, `autopilot_live` stays off.

## Testing

- `backend/tests/test_rotation.py`:
  - buys the top 8 once, through the real fence;
  - a news veto removes only that name;
  - risk-off holds cash;
  - with the autopilot off nothing is bought;
  - the plan content;
  - weekly rebalance days;
  - the backtest runs with and without the research stop and breadth filter.
- `frontend/src/utils/plan.test.js`: the plan card's headline.
