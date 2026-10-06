# Journey

How NeoTrade got here: what shipped, when, and why the direction changed. Commits per
month: Nov 2025 · 4, Dec 2025 · 34, Jan 2026 · 3, Sep 2026 · 246, Oct 2026 · 326 (to 6 Oct).

## Nov 2025 — an AI stock investor

**22 Nov.** First version: an "AI stock investor" built from LLM agents (analyst, quant,
risk) with MCP tools, deciding BUY / SELL / HOLD. **23 Nov:** moved from OpenAI to Gemini.

## Dec 2025 – Jan 2026 — the agent app grows, then pauses

**6–7 Dec.** Structured logging, a dashboard, streaming chat with visible agent thinking,
agent memory, a system-architecture page, watchlist, and the first rebrand to "NeoTrade AI".
**11 Jan:** the agent workflow re-architected for parallel execution with a synthesis node.
Then nothing for eight months.

## Sep 2026 — from agent toy to trading engine

- **5 Sep — the engine rework.** The LLM pipeline was demoted to a research-report writer;
  a two-mode engine (intraday executes, long-term proposes) took over with ported rule
  strategies and an Indian cost model. All model calls moved to the self-hosted OmniRoute
  gateway with a model picker. Google sign-in gated every route.
  *Why:* an LLM deciding trades was neither testable nor explainable.
- **6 Sep.** Kite connected for market data; the "live contract note" redesign and the
  decisions inbox.
- **9 Sep — Phases 0–3.** Renamed to **NeoTrade**. Per-user encrypted broker credentials
  (multi-tenancy), the broker adapter layer (Kite, Upstox, Angel One behind one interface),
  and the safety rails: kill switch, backtest gate, capital caps.
- **10–11 Sep — Phases 4–6.** Intraday strategies wired and really backtested; live equity
  execution with idempotent submit and fill polling; F&O plumbing and the cash-secured put;
  the long-term analyst agent revived as a strategy that emits `Intent` like everything else.
- **14 Sep — Phase 7.** Multi-worker readiness: Redis pub/sub, distributed scheduler lock,
  no process-local run state.
- **26 Sep — Phase 8, the pivot.** Repositioned as **the discipline layer on top of your
  broker**. *Why:* SEBI's studies show ~9 in 10 retail F&O traders lose money; what they
  lack is discipline and an honest review, not ideas — and the engine's own strategies were
  failing their backtest gate (orb_breakout PF 0.64), so selling their output would be
  selling losses. Same day: the trade journal (Phase 9), behaviour insights (10),
  guardrails with Telegram alerts and opt-in square-off (11), beta metrics (12), and the
  AI index-move explainer.
- **27 Sep.** Options and futures in the journal and guardrails; real holdings read from
  every broker and scored; portfolio verdicts with a weekly review; the paper gate; live
  options orders; intraday options on paper.

## Oct 2026 — accounts, AI that shows its work, a news layer

- **3 Oct.** The chat: day snapshot, read tools over your own data, confirmable action
  cards with server-side re-checks, follow-up questions. AI action plan on holdings; a year
  of Upstox history importable.
- **4 Oct — honesty and separation.** The backtester was made honest (charges, slippage,
  stamp duty) and every intraday strategy lost — so intraday became experimental and off
  by default, and an evidence-based **factor portfolio** (21.8% CAGR out of sample) went
  onto paper instead of auto-buying per-symbol ideas. The **learning loop**: pause losers,
  tighten weak signals, monthly walk-forward re-tunes with a Deflated Sharpe guard.
  **Two broker accounts**: `mine` and `ai`, orders routed by role with no fallback, and a
  fenced **autopilot** on the AI account (paper first, live behind a typed confirmation).
  Telegram became a full client of the same agent; profiles and memories; one decisions inbox.
  *Lesson:* a flattering backtester had been hiding that the strategies had no edge.
- **5 Oct — one home per kind of money.** Navigation became Today · Mine · AI · Research ·
  More; Practice moved under More. The **news and market data layer** went into its own
  ingest worker (prices, macro, ~20 feeds, triage → score → sentiment, the regime and
  brief); the **AI game plan** and its revisions; the **strategy library**; portfolio
  rebalance; LLM budgets after measuring off-hours spend.
- **6 Oct — AI on tools and a UI critique.** The fact layer and capped tool runner, with a
  grounding check on figures (Phase 16.1–16.2). Production fixes: instrument refreshes that
  starved the event loop (59k → 43 writes), tokens leaking into WebSocket log lines. A full
  UI critique (25/40) and four passes on it: money safety, plain language, phone layout,
  news noise. The gateway usage sheet made instant. This handbook and the Future backlog.

## Limits that shaped the design

| Limit, as found | How it was closed |
|---|---|
| No backtest gate — a registered strategy traded at once | Phase 3 gate, then the paper gate |
| Single-process state (`_RUNS`, hub, scheduler) | Phase 7: Redis pub/sub, locks, heartbeats |
| One LLM singleton; per-user model stored but unused | tiers per kind of task, chosen by the admin |
| `/trading/start` trusted request-body risk caps | caps read from stored prefs |
| Backtest drawdown / Sharpe hardcoded to 0 | `backend/engine/metrics.py` computes both |
| An old agent blend (`confidence×0.6 + alignment×0.4`) beside the 30% cap | removed; every source emits `Intent` into `composite.py` |
