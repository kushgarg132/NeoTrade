# AI & News

What the models do, what they are not allowed to do, and how the news layer feeds them.

## The rule that shapes everything

AI explains, scores sentiment, and suggests. It never decides a trade on its own:
its say in conviction is capped at 30% and cannot lift a trade under the rule floor
(Trading & Money). The two places model output can act are the AI account's fenced
autopilot and the game plan, which may only tighten.

## The gateway

Every model call goes through OmniRoute (`backend/llm.py::LLMService`, base URL
`OMNIROUTE_BASE_URL`, keys `OMNIROUTE_API_KEYS`). The admin picks a model per **tier**
(`backend/app_settings.py::TIERS` — `fast`, `standard`, `deep`) in Settings → AI; a tier
left empty falls back to the single default model. Settings → AI also shows the gateway
key's tokens and cost this month and each provider's remaining quota, from OmniRoute's
`/v1/me/status` (served instantly from the last reading and refreshed behind, because
OmniRoute polls every provider live, 3–5 s).

Every prompt is a file in `backend/prompts/*.md` (system prompt in front matter,
`{{placeholders}}`, rendered by `backend.prompts.render`); none are inlined in Python.

| Prompt | Tier | Used for |
|---|---|---|
| `triage_news.md` | fast | keep or drop up to 150 headlines in one call |
| `score_market_news.md` | deep | impacts for up to 40 news items in one call |
| `score_news.md` | deep | a stock's news sentiment (first of the analyst's two calls) |
| `research_report.md` | standard | the stock's research note and thesis |
| `market_brief.md` | standard | the market brief (hourly in session, only when the regime moved or material news landed) |
| `index_move.md` | standard | why an index moved in its last session |
| `game_plan*.md`, `game_plan_revision*.md` | deep | the pre-open plan and its revisions |
| `portfolio_review.md` | deep | holdings write-up and action plan |
| `learning_review.md` | standard | Friday learning note |
| `strategy_hypotheses.md` | deep | monthly threshold ideas |
| `chat.md` | deep | the margin-note chat and Telegram |
| `chat_followups.md` | fast | follow-up suggestions after a reply |
| `peers.md` | deep | peer companies for research |
| `resolve_instrument.md` | fast | name → instrument lookup |
| `model_test.md` | the model under test | Settings' "test this model" |

## Budgets

| Budget | Key | Limit |
|---|---|---|
| News scoring | `news:deep_calls:<IST day>` | `NEWS_LLM_CALLS_PER_DAY` (past it, the backlog waits for tomorrow, then goes STALE) |
| Game plans | `plan:calls:<IST day>` | `PLAN_LLM_CALLS_PER_DAY` |
| Tool rounds | per call, ≤ 4 rounds | each round spends the caller's own budget (plans: `plan:calls`); kill switch `AI_TOOLS_ENABLED` |

Chat and research calls are not counted per task.

<!-- live:ai -->

## Facts, tools and grounding

- **Fact layer** — `backend/ai/facts/`: the one read path for AI features. Market facts
  (`quote`, `price_summary`, `fundamentals`, `news`, `sentiment`, `market_backdrop`,
  `calendar`) and user facts (`portfolio`, `positions`, `journal`, `learning`,
  `strategy_library`, `game_plan`). Each returns `as_of`, `source`, and an `error` field
  instead of raising. Never query collections directly to build a prompt.
- **Tool runner** — `backend/ai/runner.py::run_with_tools`: up to 4 tool rounds, schema
  repair, budget, and a single-call fallback when tools fail.
- **Grounding** — `backend/ai/grounding.py`: figures in AI prose are checked against the facts
  the call received; dates, times and unrelated numbers are not treated as facts.

## The chat (every page, and Telegram)

`backend/chat/`: each message carries a day snapshot (`context.py`) and the trader's
profile (`backend/profile/`: name, trading profile, AI instructions, memories). Read tools
are bound to the caller's `user_id`; `query_my_data` reads allow-listed collections ANDed
with that id and never secrets (`broker_credentials`, `alert_channels`, `refresh_tokens`,
`users`, `app_settings`). Actions are **cards**: a record in `chat_actions` that does
nothing until `POST /chat/actions/{id}/confirm`, which re-runs every check (twice for a
live order). Cards on your own account go to `mine` only. The same agent answers your
linked Telegram chat (`backend/guardrails/telegram_bot.py`): one long-poller per bot under
a Redis lock, streamed replies, Confirm / Cancel buttons through the same confirm path.

## The game plan

`backend/plan/`: at 08:45–09:15 IST one `deep` call per auto-intraday user builds a plan
(allowed strategies and names, `risk_multiplier`, `max_positions`, `skip_day`), validated so
it can only tighten; any failure stores a fallback plan. During the session `plan_revise`
(ingest, 60 s) revises on material news about a planned or held name, a regime change, or a
high-impact event — at most 6 a day, 15 min apart. Since Phase 16.2 the plan fetches its
facts through tools first. The 16:00 pass replays each day with and without the plan.

## News

Ingest loops in `backend/datalayer/`:

1. **Collect** — `news_poll` (60 s): ~20 RSS feeds (ET, Moneycontrol, Mint, RBI, SEBI, PIB,
   CNBC, BBC, Google News), Google News searches (market, macro, each NSE industry every
   15 min, held/watched names every 15 min, the Nifty 200 round-robin), GDELT global events
   (5 min) and NSE corporate filings. Each story is stored once in `news_items` (id = hash of
   the normalised title); company symbols are tagged by name, unique first word and ticker
   (`news.py::build_aliases`).
2. **Triage** — `news_process` (5 min): one fast call keeps anything that could move Indian
   stocks. Dropped items live 7 days; kept items 2 years as learning data. NSE filings skip triage.
   Before scoring, `news.py::_prune` also drops (with `skip_reason`) rewrites of a story scored or
   queued in the last day (title word overlap ≥ 0.7), company news naming no followed symbol, and
   non-Latin-script copies.
3. **Score** — one deep call gives each item `impacts[]` on the market (`INDIA`), an NSE
   industry, or a followed symbol; impact ≥ 6 marks it `material`. Unscored after 3 days → STALE.
4. **Aggregate** — from 60 days of impacts (impact² weight, 30-day half-life):
   `sentiment:<SYM>` = 0.6 company + 0.25 sector + 0.15 market (the single `ai_score` the
   composite caps at 30%), plus sector and market sentiment and `analyst_verdict:<SYM>`.
5. **React** — `news_react` (60 s): each new material item alerts users by their `news_alerts`
   pref (held / held+watched / all / off), one alert per user and target an hour, by
   Telegram and an in-app toast. `news_scan` (120 s) re-scans the names it moves for new
   long-term proposals; `news_exits` only shadow-logs what the autopilot would sell.
6. **Learn** — `news_outcomes` (5 min): each material item's move at +1 h, +1 d, +5 d against
   Nifty; weekly theme weights (0.5–1.5) shift influence between items, never the range.

**The backdrop** — `regime` (60 s, no LLM) scores risk-on / neutral / risk-off from news
sentiment, India VIX, Brent, USD/INR, S&P futures, FII flows and imminent high-impact
events; `brief` writes the market brief. Both feed research notes, the chat, the plan and
the autopilot fence.

**What you see** — Research → News (`GET /news/feed`: your names by default — paper
positions, broker holdings and the watchlist — filings that move nothing left out),
`NewsChip` on Holdings, Watchlist, Scanner and Decisions (`GET /news/symbols`), and Today's
Markets card.

<!-- live:news -->
