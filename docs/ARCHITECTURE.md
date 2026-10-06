# NeoTrade — architecture

Moved 2026-10-06 into the handbook, which the app also shows at `/system` (admin-only) with
live status beside it:

| Section | File |
|---|---|
| System map, brokers, market data, where data lives | [`frontend/src/handbook/system-and-data.md`](../frontend/src/handbook/system-and-data.md) |
| Accounts, the decision pipeline, invariants, gates, autopilot | [`frontend/src/handbook/trading-and-money.md`](../frontend/src/handbook/trading-and-money.md) |
| LLM gateway, prompts, budgets, fact layer, chat, game plan, news | [`frontend/src/handbook/ai-and-news.md`](../frontend/src/handbook/ai-and-news.md) |
| Daily pass, loops, ingest, deploys, auth, secrets, logs | [`frontend/src/handbook/jobs-and-ops.md`](../frontend/src/handbook/jobs-and-ops.md) |
| How it got here, and the limits that shaped it | [`frontend/src/handbook/journey.md`](../frontend/src/handbook/journey.md) |

Dated specs and plans under `docs/superpowers/` still cite this file's old section numbers;
they describe the code as it was when written.
