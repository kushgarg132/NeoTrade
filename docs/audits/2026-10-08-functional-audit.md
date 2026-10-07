# Functional audit — 2026-10-08

Scope: frontend↔backend API contract, handbook anchors, eslint, production data and job
marks, and a read of the money paths (kill switch, approvals, autopilot, exits,
guardrails, Today, live/stale). Per-user isolation and the API contract were clean.
Status column is updated as fixes land.

| # | Severity | Finding | Where | Status |
|---|---|---|---|---|
| 1 | Critical | Daily loss limit 0 trips the engine kill switch on the first bar (`should_trip(eq, 0)` is `eq <= 0`); Settings says 0 turns it off; the autopilot treats 0 as off. API accepts negative limits. | `engine/runner.py:500`, `risk/kill_switch.py:12`, `routers/settings.py:68` | open |
| 2 | Critical | A live approval sends only a MARKET order; no stop order, and `check_exits` reads `venue="paper"` only, so stop/target/max hold are never enforced on real positions. | `routers/suggestions.py`, `suggestions/exits.py` | open |
| 3 | Critical | Guardrails (the user's own rules) count every connected broker, the AI account included: AI losses trip the user's guardrail and kill switch (blocking the user's live approvals); live auto square-off places orders on the AI account. Live in production (only Kite, role `ai`, is logged in). | `guardrails/monitor.py` | open |
| 4 | Critical | Turning the autopilot off strands its positions: the fence refuses every order (exits too) while off, autopilot exits only run while on, and the engine's exit check skips autopilot trades. | `autopilot/fence.py:49`, `engine/autorun.py:292`, `suggestions/exits.py:122` | open |
| 5 | High | Intraday MIS paper positions held overnight (ASHOKLEY, RELIANCE, VOLTAS, 2026-10-07): their run was orphaned by a 13:00 IST restart; the next run got zero bars, so the 15:15 square-off never fired. Nothing detects a run that receives no bars. | `engine/runner.py`, `engine/autorun.py` | open |
| 6 | High | Container logs are lost on every recreate, so item 5 cannot be diagnosed. | `docker-compose.yml` | open |
| 7 | High | The engine kill switch measures only the current run's portfolio; a restart carries open positions but not the day's realized P&L, so losses across restarts can pass the limit untripped. | `engine/runner.py`, `engine/adopt.py` | open |
| 8 | High | Paper autopilot trades sit in the Practice book and Practice P&L / scorecard do not exclude them, while AI Overview counts them too — the same money in two homes. | `analytics.py`, `autopilot/service.py:36` | open |
| 9 | High | AI Overview, AI Activity and Mine Holdings load once: no live topic, no polling, no refetch on reconnect, while the masthead says Live. | `frontend/src/pages/AiOverview.jsx`, `AiActivity.jsx`, `MyPortfolio.jsx` | open |
| 10 | Medium | Live fills are recorded with `costs=0.0`, so live P&L is gross while paper is net of charges. | `engine/reconcile.py:52`, `engine/execution/broker.py:86`, `suggestions/service.py:145` | open |
| 11 | Medium | Paper approvals have no market-hours, per-trade cap, exposure or already-held check (BHEL filled 02:15 IST at a stale price); the scan proposes buys of symbols already held. These fills count toward the paper gate. | `routers/suggestions.py`, `suggestions/sink.py:46` | open |
| 12 | Medium | Daily bars come from Yahoo (Kite has no historical add-on, Upstox logged out): a day late and with holiday bars; data_quality reported 227 stale symbols with ok=1 and no alert. | `datalayer/bars.py`, `system/data_quality.py` | open |
| 13 | Medium | No NSE holiday calendar: on a holiday the UI says Session open, live approvals pass the hours check, the autopilot fence treats the market as open. | `engine/autorun.py:67`, `frontend/src/utils/formatters.js:98` | open |
| 14 | Medium | Session windows disagree: guardrails 09:15–15:35, engine 09:15–15:30, UI 09:15–15:30 with pre-open from 09:00. | `guardrails/monitor.py`, `engine/autorun.py`, `utils/formatters.js` | open |
| 15 | Low | The autopilot log row for TRENT has no `suggestion_id` while its trade has one; the proposal says 2 shares, 1 filled. | `autopilot/service.py` | open |
| 16 | Low | Today's kill-switch line says "live trading stopped" but it also stops paper entries. | `routers/today.py` | open |
| 17 | Low | Unused frontend endpoint keys: `stockInfo`, `marketNews`, `trading.equity`, `broker.list`. | `frontend/src/utils/api.js` | open |
| 18 | Low | `live_kite.py` docstring says the feed is not used; it is the live intraday feed. | `data/feeds/live_kite.py` | open |
| 19 | Low | eslint: `TradingChart.jsx:49` setState in effect; `vite.config.js:8` `process` undefined; 3 exhaustive-deps warnings. | frontend | open |

Owner to-dos: log in to Upstox (role `mine`); decide whether Kite needs the historical-data add-on.
