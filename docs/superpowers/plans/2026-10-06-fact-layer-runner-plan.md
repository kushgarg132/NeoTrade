# Fact Layer, Tool Runner and Grounding Check Implementation Plan (Phase 16.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One read-only fact layer every AI feature uses, a capped tool-calling runner, a grounding check for figures, and chat's read tools rebuilt on the facts — the foundation later phases migrate call sites onto.

**Architecture:** `backend/ai/facts/` holds async fact functions with one signature and a registry that turns them into LangChain tools. `backend/ai/runner.py` drives a bounded tool loop over `llm_service.get_llm(tier).bind_tools(...)` with per-round budget, schema repair and single-call fallback. `backend/ai/grounding.py` checks figures in prose against the numbers the call received. Chat keeps its tool names but delegates to facts.

**Tech Stack:** Python 3.11, LangChain core (`StructuredTool`, `AIMessage.tool_calls`, `ToolMessage`), Motor/mongomock, Redis/FakeRedis, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-ai-tools-fact-layer-design.md` (sections 1, 2, 4, 5; rollout step 1)

## Global Constraints

- Fact signature: `async def fact(db, redis, user_id: Optional[str], **args) -> dict`; every result has `as_of` (ISO UTC) and `source`; failures return `{"error": str, "as_of": ...}` and never raise.
- User facts always filter by `user_id`; market facts ignore it. Facts are read-only.
- Runner: `max_rounds` default **4**; budget `AI_TOOL_CALLS_PER_DAY` default **300** in Redis `ai:calls:<IST date>`; `AI_TOOLS_ENABLED` default **True**.
- Grounding tolerance: ±0.5 % relative; percentages ±1 in the last shown digit; dates, times and years ignored.
- No call site other than chat changes in 16.1.
- Tests: `cd /home/ubuntu/projects/NeoTrade && python3 -m pytest backend/tests -q -p no:cacheprovider`. Deploy: direct (`[skip ci]`; rebuild `backend`).

## Decisions this plan makes

- `index_move` fact is deferred to 16.4 (it needs `research/index_move.py` split into data + LLM halves, which is that phase's work). Chat's `explain_index` stays as is.
- Chat-only tools with no spec fact (`get_paper`, `get_decisions`, `get_limits`, `query_my_data`) are unchanged.
- `news` fact takes an optional `query` (title search) so chat's `search_news` can delegate; chat keeps its on-demand web fallback for unfollowed symbols.

## Review Focus

1. A fact for an unknown symbol (no bars, no fundamentals) → `{"error": ...}` with `as_of`, never an exception. Pinned in Task 1.
2. Model asks for a tool name that does not exist, or passes bad args → a `ToolMessage` with the error; loop continues. Pinned in Task 4.
3. Model never stops calling tools → after `max_rounds` one forced no-tools answer. Pinned in Task 4.
4. Grounding on text quoting a percentage the data shows with more decimals (data 2.347, text "2.3%") → supported. Pinned in Task 5.
5. A user fact called with another user's id never returns the first user's data (scoping by argument, not by global). Pinned in Task 2.

---

### Task 1: Fact registry and market facts

**Files:** Create `backend/ai/__init__.py`, `backend/ai/facts/__init__.py` (registry), `backend/ai/facts/market.py`; Test `backend/tests/test_ai_facts_market.py`.

**Interfaces — Produces:**
- `@dataclass(frozen=True) class Fact: name: str; fn: Callable; description: str; user: bool`
- `FACTS: dict[str, Fact]`; decorator `fact(name, description, user=False)` registers.
- `def as_tools(db, redis, user_id: Optional[str], names: list[str]) -> list[StructuredTool]` — each tool calls the fact, returns compact JSON (`json.dumps(default=str)`); args schema inferred from the fact's keyword params (`StructuredTool.from_function(coroutine=...)` on a closure with the same signature minus `db, redis, user_id`).
- Market facts (names exactly): `quote(symbol)`, `price_summary(symbol, days=60)`, `fundamentals(symbol)`, `news(symbol=None, sector=None, scope=None, query=None, hours=48, material_only=False, limit=10)`, `sentiment(symbol)`, `market_backdrop()`, `calendar(hours=48)`.
- `price_summary` fields: `last_close`, `ret_1d/5d/20d/60d` (%), `high_52w`, `low_52w`, `sma_20/50/200`, `atr_14`, `bars` (count) from `datalayer.bars.read`; `news` rows: `title, published_at, scope, impacts (only for the asked target when symbol/sector given), material, url`, limit ≤ 30, hours ≤ 24·60.

- [ ] Step 1: failing tests — `test_registry_lists_every_market_fact_and_builds_tools` (7 names; `as_tools` returns StructuredTools whose names match), `test_price_summary_from_daily_bars` (seed 250 bars → sma_200 present, ret_20d correct), `test_unknown_symbol_returns_an_error_not_an_exception` (quote/price_summary/fundamentals), `test_news_filters_and_trims_impacts`, `test_backdrop_reads_regime_brief_flows`.
- [ ] Step 2: run — FAIL. Step 3: implement (wrap existing readers: `marks.mark_prices`, `bars.read`, `StoreFundamentals(db, fallback=None-safe)` reading the store only, `news_items`, `ai.sentiment.get_cached_sentiment` + sector/market keys, `datalayer.market.backdrop` + `prices.macro_rows` + flows, `market.upcoming`). Step 4: PASS.
- [ ] Step 5: commit `feat(ai): fact layer -- market facts and tool registry [skip ci]`

---

### Task 2: User facts

**Files:** Create `backend/ai/facts/user.py`; Test `backend/tests/test_ai_facts_user.py`.

**Interfaces — Produces (all `user=True`):** `portfolio(symbol=None, account="all")`, `positions(venue="paper")`, `strategy_library(mode=None)`, `game_plan()`, `learning()`, `journal(period="month", symbol=None, account="all")`. Bodies are the logic now inside `chat/tools.py` `get_portfolio`, `get_journal` (with `attach_news`), `get_learning`, `get_strategy_library`, returned as dicts (not JSON strings); `positions` from `LedgerStore(db, user_id).get_open_positions(venue)`; `game_plan` = `plan.store.current` + today's versions (trigger, at, rationale).

- [ ] Step 1: failing tests — `test_user_facts_are_scoped_to_the_user_id` (alice and bob positions/plans seeded; each sees only their own), `test_portfolio_without_snapshot_is_an_error_dict`, `test_game_plan_lists_versions`.
- [ ] Step 2–4: FAIL → implement → PASS.
- [ ] Step 5: commit `feat(ai): fact layer -- user facts [skip ci]`

---

### Task 3: Chat's read tools on the facts

**Files:** Modify `backend/chat/tools.py` (`read_tools`).

**Interfaces — Consumes:** Tasks 1–2. `get_portfolio`, `get_journal`, `get_learning`, `get_strategy_library`, `get_market_backdrop` become thin wrappers: call the fact, return `_json(result)` (portfolio keeps its "No portfolio has been analysed yet…" text when the fact returns its error). `search_news` calls `news(...)` (days → hours) and keeps its unfollowed-symbol web fallback. Names, args and descriptions unchanged.

- [ ] Step 1: run existing `test_chat_tools.py test_chat_query_tool.py test_chat_agent.py` — PASS before (baseline).
- [ ] Step 2: add `test_chat_and_facts_return_the_same_portfolio` (same seeded snapshot → `json.loads(get_portfolio())` equals the fact's dict minus `as_of/source`); run — FAIL.
- [ ] Step 3: refactor. Step 4: chat tests + new test PASS.
- [ ] Step 5: commit `refactor(chat): read tools come from the shared fact layer [skip ci]`

---

### Task 4: Tool runner

**Files:** Create `backend/ai/runner.py`; modify `backend/configs/settings.py` (`AI_TOOL_CALLS_PER_DAY: int = 300`, `AI_TOOLS_ENABLED: bool = True`); Test `backend/tests/test_ai_runner.py`.

**Interfaces — Produces:**
- `async def reserve_ai_call(redis, now) -> bool` (Redis `ai:calls:<IST date>`, same pattern as `plan.store.reserve_call`).
- `async def run_with_tools(task: str, *, system: str, prompt: str, tools: list, tier: str, schema: Optional[type[BaseModel]] = None, max_rounds: int = 4, reserve: Optional[Callable[[], Awaitable[bool]]] = None, fallback: Optional[Callable[[], Awaitable[str]]] = None, llm=None) -> dict` → `{"output": str | BaseModel | None, "tool_trace": list[dict], "rounds": int, "facts": list[dict], "used_fallback": bool}`. `llm` injectable for tests (default `await llm_service.get_llm(tier)`). `facts` = every tool result dict (for grounding).

Loop: messages `[System, Human]`; each round: `reserve()` False → break to final; `ai = await bound.ainvoke(messages)`; no `tool_calls` → final; else run calls concurrently (`asyncio.gather`), append `ToolMessage(content, tool_call_id)` (unknown tool / exception → content `{"error": ...}`). After `max_rounds` or budget stop: one `llm.ainvoke(messages + [Human("Answer now from what you have; no more tools.")])` unbound. `schema`: parse final content JSON into the model; on failure one repair turn ("Return only valid JSON for: <schema json>"); still invalid → `output=None`. `AI_TOOLS_ENABLED` False, `llm` None, or any exception from the provider → `fallback()` if given (`used_fallback=True`), else `output=None`.

- [ ] Step 1: failing tests with a scripted fake LLM (`bind_tools` returns itself; `ainvoke` pops scripted `AIMessage`s): `test_runs_tools_then_answers`, `test_unknown_tool_and_bad_args_become_error_messages`, `test_stops_after_max_rounds_with_a_forced_answer`, `test_budget_cut_forces_the_final_answer`, `test_schema_repair_then_none`, `test_provider_error_uses_the_fallback`, `test_kill_switch_uses_the_fallback`.
- [ ] Step 2–4: FAIL → implement → PASS.
- [ ] Step 5: commit `feat(ai): capped tool-calling runner with budget, schema repair and fallback [skip ci]`

---

### Task 5: Grounding check

**Files:** Create `backend/ai/grounding.py`; Test `backend/tests/test_ai_grounding.py`.

**Interfaces — Produces:**
- `def figures(text: str) -> list[tuple[str, float, int]]` — (raw token, value, decimals shown) for numbers with ≥ 2 significant digits or a `%`/`₹` marker; skips dates (`2026-10-06`, `06 Oct`, `Oct 6`), times (`09:15`), years 1900–2100 standing alone, and list markers.
- `def numbers_in(facts: list) -> list[float]` — every numeric leaf in nested dicts/lists (strings that parse as numbers included).
- `def unsupported(text: str, facts: list) -> list[str]` — raw tokens with no match: relative diff ≤ 0.5 %, or for `%` tokens |value − x| ≤ 10^(−decimals) (so "2.3%" matches 2.347).
- `def strip_unsupported(text: str, tokens: list[str]) -> str` — drops sentences containing any token.
- `async def grounded(text, facts, retry: Optional[Callable[[list[str]], Awaitable[str]]]) -> tuple[str, bool]` — unsupported → one `retry(tokens)`; still unsupported → strip, `False`.

- [ ] Step 1: failing tests: `test_fabricated_price_is_caught`, `test_rounding_and_percent_precision_pass`, `test_dates_times_years_are_ignored`, `test_retry_then_strip`.
- [ ] Step 2–4: FAIL → implement → PASS.
- [ ] Step 5: commit `feat(ai): grounding check for figures in AI prose [skip ci]`

---

### Task 6: Docs, deploy, verify

- [ ] ARCHITECTURE (fact layer + runner + grounding paragraph), ROADMAP (16.1 done), `.claude/CLAUDE.md` line: "AI features read data through `backend/ai/facts/`; never query collections for a prompt directly".
- [ ] Full suite PASS; commit + push; rebuild `backend`.
- [ ] Verify on prod: in the container, `as_tools(db, redis, <real user>, ["quote","price_summary","news","portfolio"])` returns 4 tools and each invocation for `HDFCBANK` / the user returns a dict with `as_of`; one real chat question through `/chat` (or the agent function) answers without error.
