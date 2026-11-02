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

**Agents: start with the wiki, not the code.** `docs/wiki/INDEX.md` maps every area to a
code-anchored page. Run `python3 docs/wiki/stale.py` first: trust current pages and open only
the files you will change; for stale pages read only the changed files it lists. Before a
whole-app scan or audit, run the `wiki-sync` skill. A code change updates its page's section
and `verified_at` in the same commit.

| Question | Document |
|---|---|
| Where is X, what calls Y, what runs when? | `docs/wiki/` (agent wiki, see above) |
| What is this product, who uses it, what are the states that matter? | `PRODUCT.md` |
| How does the code actually work? | `frontend/src/handbook/*.md` — the handbook, also in the app at `/system` |
| **What should I work on right now?** | The backlog (see below): `doing`, then `next`. `docs/ROADMAP.md` keeps the long-term phases |
| What should this look like? | `DESIGN.md` (tokens are real, in `frontend/src/index.css`) |

The handbook (`frontend/src/handbook/`) is verified against the code with `file::symbol` anchors. If it and
the code disagree, the code is right — fix the handbook in the same commit.

## Backlog: update it first, keep it current (mandatory)

The backlog (`backlog` collection, shown at `/lab/backlog`) is the record of what is being worked
on. Any session that will change this repo updates it **before the first edit**, not at the end.
Read-only questions and investigation with no change need no item.

```bash
B="docker exec neotrade-backend python -m backend.system.backlog_cli"
$B list                                   # open items; --all adds done and dropped
$B show <id>                              # one item in full
$B add "Title" --area UI --status doing --why "what the owner asked for" --source "session 2026-11-02"
$B set <id> --status done --notes "..."   # --notes replaces: show first, then keep what still matters
```

1. **Before editing:** run `list`. Set the matching item to `doing`, or `add` one as `doing`. An
   item already `doing` may be another session's: read its notes before touching that work.
2. **While working:** update `notes` when the scope or plan changes. Add follow-ups you find but
   will not do now as `idea`, instead of leaving them in chat.
3. **When it lands:** set `done` with the commit in `notes`. If you stop before that, leave it
   `doing` with notes saying what is finished and what is left.

The session that talks to the owner keeps the backlog. Subagents do not touch it. Areas:
System, Data, Trading, AI, News, Journal, UI, Ops, Product.

## Invariants — never break these silently

- **AI is capped at 30% of conviction, and currently weighted 0 in sizing** (`AI_SIZING_WEIGHT = 0.0`,
  owner decision 2026-10-24, until validated). `AI_CAP = 0.30`, clamped inside a frozen dataclass
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
  Since 2026-11-02 (owner-approved) the autopilot's only entry source is the weekly rotation
  (`backend/autopilot/rotation.py`); engine, news and Picks proposals no longer reach it.
  News only vetoes rotation buys (bad sentiment, results due); news exits are shadow-logged only.
  The fence's regime rule (risk-off halves the cap; a high-impact event within 30 min blocks
  all entries) only ever tightens. See `docs/superpowers/specs/2026-11-02-rotation-autopilot-design.md`.
- **The AI game plan only tightens.** `backend/plan/` (built from 08:45 IST per auto-intraday user with a live feed)
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
