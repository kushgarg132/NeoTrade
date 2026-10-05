# NeoTrade

The discipline layer on top of an Indian trader's own broker (Kite / Upstox / Angel One):
an auto-imported trade journal, behaviour findings over it, and self-set guardrails
(`backend/journal/`, `/journal`). Nothing sold here is advice — see `PRODUCT.md`.

A strategy engine also exists as a secondary, free feature: it emits fully-formed trades —
size, entry, stop, target, the rule codes that fired, and a composite score — then either
executes them (intraday) or routes them to an approval inbox (long-term), per strategy on
paper or live.

FastAPI + MongoDB + Redis backend on this VM; React 19 + Vite frontend on Vercel.

## Read these, in this order

| Question | Document |
|---|---|
| What is this product, who uses it, what are the states that matter? | `PRODUCT.md` |
| How does the code actually work, and where is it going? | `docs/ARCHITECTURE.md` |
| **What should I work on right now?** | `docs/ROADMAP.md` — check the Status column |
| What should this look like? | `DESIGN.md` (tokens are real, in `frontend/src/index.css`) |

`docs/ARCHITECTURE.md` §1 is verified against the code with file:line anchors. If it and the
code disagree, the code is right — fix the document in the same commit.

## Invariants — never break these silently

- **AI is capped at 30% of conviction.** `AI_CAP = 0.30`, clamped inside a frozen dataclass
  at `backend/scoring/composite.py:15,25-30`. Not a convention — enforced and tested.
- **AI cannot rescue a trade the rules did not support.** `RULE_FLOOR = 0.45`;
  `score_intent()` returns `None` below it.
- **Exactly one conviction formula exists.** Any new idea source emits `Intent` and is scored
  by `composite.py`. Never add a second blend.
- **Every intent carries non-empty `reason_codes`.** A trade with no explanation cannot exist.
- **Every per-account record carries `user_id`.** This app is multi-user; nothing may be
  keyed on "the operator".
- **Position sizing lives in `size_intents` + `RiskRules`, never inside a strategy.**
- The daily loss kill-switch (`backend/risk/kill_switch.py`) and the backtest gate
  (`backend/risk/backtest_gate.py`) are enforced in code, not by discipline. Do not add a
  code path that routes around either.
- **The AI account's autopilot is the one exception to the backtest gate and to "model output
  never places an order".**
  Exception (user-approved 2026-10-04): `backend/autopilot/` may place orders without a user tap
  on the broker whose role is `ai` (`backend/brokers/roles.py`) only, after `autopilot/fence.check`
  passes; the kill switch still applies, and nothing may route an AI order to the user's own
  (`mine`) account. See `docs/superpowers/specs/2026-10-04-dual-broker-accounts-design.md`.
  Extended (user-approved 2026-10-05): with pref `autopilot_news` on, a `source="news"`
  proposal may go to the autopilot at once (≤3 a day); news exits are shadow-logged only.
  The fence's regime rule (risk-off halves the cap and blocks news entries; a high-impact
  event within 30 min blocks all entries) only ever tightens. See
  `docs/superpowers/specs/2026-10-05-autopilot-news-design.md`.
- **The AI game plan only tightens.** `backend/plan/` (built 08:45 IST per auto-intraday user)
  may drop opening intraday intents, shrink their risk (`risk_multiplier` 0.25–1.0), cap new
  positions or skip the auto run; it never blocks or shrinks an exit, never touches
  conviction, caps or gates, and any failure falls back to today's behaviour. A revision may
  close strategy-opened **paper** engine positions (never hand trades); on the AI account it
  is only logged to `autopilot_shadow` (`source="plan"`). See
  `docs/superpowers/specs/2026-10-05-ai-game-plan-and-strategy-library-design.md`.

## Deployment

Backend runs on this VM under Docker Compose behind Nginx + Let's Encrypt; frontend on
Vercel. Both halves are push-to-deploy from `main` — the backend via a self-hosted GitHub
Actions runner (gated on CI passing, rebuilds only when `backend/` or `docker-compose.yml`
changed), the frontend via Vercel's git integration. **Prefer the pipeline over deploying by
hand**; verify with `gh run watch <id> --exit-status` plus a health check rather than racing
it with a manual build. See `/home/ubuntu/CLAUDE.md` for ports, URLs, and host-level detail.

## Working here

- System `mvn` is irrelevant here; this is Python. Backend tests: `cd backend && python -m pytest`.
- `vitest` alone is not a build check on the frontend — run `npm run build` too.
- Background long builds and test runs rather than idling on them.
- AI features read data through `backend/ai/facts/` (as prompt context or as tools via
  `ai/runner.run_with_tools`); never query collections directly to build a prompt.
- Every LLM prompt lives in `backend/prompts/*.md` (system prompt in front matter,
  `{{placeholders}}`), rendered by `backend.prompts.render`. Never inline a prompt in a `.py` file.
- Commit and push in the same session; split unrelated changes into separate commits.
