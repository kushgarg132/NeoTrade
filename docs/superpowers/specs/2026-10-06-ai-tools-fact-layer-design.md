# AI on tools: one fact layer, a capped tool runner, and a grounding check

User-approved design, 2026-10-06.

## Intent

Every LLM call site except chat packs its own data into the prompt. The user sees four
problems: made-up facts, features disagreeing about the same stock or market, calls that lack
data they needed, and bloated prompts. Goal: every AI feature reads the same facts the same
way, analysis-style calls fetch what they need through tools, and figures the AI states are
checked against the data it was given.

Constraint: tools only where they pay (agreed). Batch labellers stay one call. Extra usage
≈ +30–60 calls/day at current volume, always inside a daily budget.

Success: no AI output states a figure absent from its data; chat, plan, analyst and portfolio
review quote identical numbers for the same stock at the same time; prompts for migrated sites
shrink to a seed plus tool results.

## 1. Fact layer — `backend/ai/facts/`

One async function per fact: `fact(db, redis, user_id, **args) -> dict`. Every result carries
`as_of` (ISO UTC) and `source`; fields are compact (no article bodies). Market facts ignore
`user_id`; user facts always filter by it. A failed read returns
`{"error": "<short reason>", "as_of": ...}` and never raises. Facts wrap the existing readers;
nothing is reimplemented.

| Fact | Reads |
|---|---|
| `quote(symbol)` | `marks.mark_prices` / `quote:` cache |
| `price_summary(symbol, days=60)` | `daily_bars`: last close, 1/5/20/60-day % returns, 52-week high/low, 20/50/200-day SMA, ATR(14) |
| `fundamentals(symbol)` | `fundamentals` store |
| `news(symbol=None, sector=None, scope=None, hours=48, material_only=False, limit=10)` | `news_items` (title, impacts for the target, published_at) |
| `sentiment(symbol)` | `sentiment:{SYM}` + `sector_sentiment:{S}` + `market:sentiment` |
| `market_backdrop()` | `market:regime`, `market:brief`, macro board, `market:flows`, sector sentiment |
| `calendar(hours=48)` | `econ_calendar` (high impact) |
| `portfolio(account="all")` | latest portfolio snapshot for the user |
| `positions(venue="paper")` | ledger open positions for the user |
| `strategy_library(mode=None)` | `learning/library.catalog` |
| `game_plan()` | `plan/store.current` + today's versions |
| `learning()` | `learning/report.snapshot` |
| `journal(period="month")` | journal round trips + insights (with `attach_news`) |
| `index_move(ticker)` | the data-gathering half of `research/index_move` (no LLM) |

Chat's read tools are rebuilt on these facts; tool names and descriptions stay, so chat
behaviour does not change. Chat's action tools are untouched; the fact layer is read-only.

## 2. Tool runner — `backend/ai/runner.py`

`run_with_tools(task, *, system, prompt, tools, tier, schema=None, max_rounds=4, budget=None)
-> {"output", "tool_trace", "rounds", "grounded"}`

- Binds facts as LangChain tools (`MultiKeyChain.bind_tools`); loop: model → tool calls run
  concurrently → model, until a final answer or `max_rounds`.
- Every model call reserves one call from `budget` (the plan budget for plan sites; else the
  new `AI_TOOL_CALLS_PER_DAY`, default 300, Redis `ai:calls:<IST date>`) — tool rounds, the
  final turn and the repair turn alike. `max_rounds` hit or the budget refusing a round → one
  final turn answering from what it has, *if that turn can be reserved*; otherwise no answer
  and the caller falls back (amended 2026-10-06, 16.2 review: an unbudgeted final turn let a
  spent budget keep spending).
- `schema` (pydantic): final answer validated, one repair retry.
- Provider rejects tools, or anything raises → falls back once to the site's single-call prompt
  built from facts. A failure never leaves a feature empty.
- `AI_TOOLS_ENABLED` (setting, default true) = off sends every site down the single-call path.
- `tool_trace` (tool, args, ms, error?) is logged per call site.

## 3. Call sites

| Site | After |
|---|---|
| Plan builder + revision (`plan/builder.py`, `plan/revise.py`) | seed (regime, candidates with sentiment/catalyst, card summaries, caps) + tools `price_summary`, `news`, `fundamentals`, `positions`; schema = `TradePlan` input; plan budget |
| Analyst verdict + report (`components/analyst/agent.py`) | tools `price_summary`, `fundamentals`, `news`, `sentiment`, `market_backdrop` |
| Portfolio weekly review (`portfolio/review.py`) | tools `portfolio`, `news`, `price_summary`, `market_backdrop` |
| Index move (`research/index_move.py`) | tools `index_move`, `news`, `market_backdrop` |
| Learning report + hypotheses (`learning/report.py`, `learning/hypotheses.py`) | tools `learning`, `strategy_library`, `journal` |
| Chat (`chat/tools.py` read tools) | same tools, rebuilt on facts |
| News triage/scoring, market brief, symbol resolution, chat follow-ups, model test | stay single-call; any market data in their prompts comes from facts |

Every prompt stays in `backend/prompts/*.md`; migrated prompts lose their data placeholders
and gain a line naming the tools and "state only figures you got from a tool or the seed".

## 4. Grounding check — `backend/ai/grounding.py`

For tool-run prose outputs (analyst report, portfolio review, index explanation, learning
report) and the `rationale` lines of structured outputs (plan, analyst verdict):

- Extract figures: prices, percentages, ₹ amounts, counts ≥ 2 digits; ignore dates, times,
  years, and numbers inside the site's own fixed copy.
- Each figure must match a number in that call's tool results or seed within ±0.5% relative
  (percentages: ±1 in the last shown digit).
- Unsupported figures → one retry naming them; still unsupported → those sentences are dropped
  and the run is logged `grounded: false`.

Structured fields are already validated by their own validators (e.g. `plan/validate.py`).

## 5. Testing

- Facts: contract tests on fake data (shape, `as_of`, errors never raise, user scoping).
- Runner: a fake model that requests tools then answers — loop, `max_rounds`, budget cutoff,
  schema repair, fallback on tool error, kill switch.
- Grounding: fabricated figure caught; rounding and dates pass.
- Each migrated site: existing tests + one fake-model run asserting the tools it calls.

## 6. Rollout (each step deployed and checked on prod before the next)

1. Fact layer, runner, grounding; chat moved onto facts.
2. Plan builder + revision.
3. Analyst verdict + report.
4. Portfolio review, index move, learning report + hypotheses.
5. Single-call sites read market context through facts.

## Out of scope

- Tools for batch labellers (news triage/scoring), symbol resolution, the brief.
- A separate MCP tool server.
- Any write/action capability in the fact layer.
