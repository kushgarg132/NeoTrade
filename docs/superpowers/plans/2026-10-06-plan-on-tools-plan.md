# Game Plan on Tools Implementation Plan (Phase 16.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pre-open game plan and its revisions fetch what they need through fact tools (`ai/runner.run_with_tools`) instead of a pre-stuffed prompt, with rationale figures grounded, and today's single-call path kept as the fallback.

**Architecture:** `build_plan` / `revise_plan` first run the tool loop with a compact seed (regime, candidates with sentiment/catalyst, strategy cards, caps; for revisions: trigger, plan, positions) and plan-budget `reserve`; the structured reply is validated by the existing `validate()`, its `rationale` lines pass the grounding check, and it is saved as before. Tool loop off, failing or unusable → the existing single-call code runs unchanged.

**Tech Stack:** Python 3.11, LangChain core, pydantic, pytest (scripted fake LLM from `test_ai_runner.py`).

**Spec:** `docs/superpowers/specs/2026-10-06-ai-tools-fact-layer-design.md` (section 3 row "Plan builder + revision", section 4, rollout step 2)

## Global Constraints

- Plan tools: `price_summary`, `news`, `fundamentals`, `positions` (builder); `news`, `price_summary`, `positions` (revision). `max_rounds=4`.
- Every model round reserves from the **plan** budget (`plan.store.reserve_call`, `PLAN_LLM_CALLS_PER_DAY`).
- The plan still only tightens: `validate()` is unchanged and remains the gate for every reply.
- Rationale lines with figures not found in the facts or seed are dropped (grounding); structured fields are validated, not grounded.
- Single-call path stays byte-for-byte the current behaviour and is used when tools are off, the runner returns no output, or the reply fails `validate()`.
- Prompts in `backend/prompts/`: new `game_plan_tools.md`, `game_plan_revision_tools.md`; registry tests updated.
- Tests: full backend suite. Deploy: direct, rebuild `backend ingest` (revisions run in ingest).

## Review Focus

1. Tool loop returns a reply that fails `validate()` (bad JSON shape) → single-call path still runs once, plan always stored. Pinned in Task 1.
2. Budget runs out mid tool loop → no further calls; the single-call fallback also respects the budget (stores the fallback plan). Pinned in Task 1.
3. Rationale entirely unsupported → plan stored with an empty rationale rather than invented figures. Pinned in Task 1.
4. Revision tool path with no open positions → `positions` tool returns an empty list, revision still proceeds. Pinned in Task 2.
5. Seed figures (e.g. regime score in plain text) count as supported for grounding. Pinned in Task 1.

---

### Task 1: Builder on tools

**Files:** Modify `backend/plan/builder.py`, `backend/ai/grounding.py` (`numbers_in` also reads numbers inside free text); Create `backend/prompts/game_plan_tools.md`; modify `backend/tests/test_prompts.py`; Test `backend/tests/test_plan_builder_tools.py`.

**Interfaces — Produces:**
- `class PlanReply(BaseModel)` in `builder.py`: `allow: list[dict] = []`, `add_symbols: list[str] = []`, `risk_multiplier: float = 1.0`, `max_positions: int = 10`, `skip_day: bool = False`, `rationale: list[str] = []`, `exits: list[dict] = []` (extra ignored).
- `def ground_rationale(lines: list[str], facts: list) -> list[str]` (drops lines with unsupported figures).
- `build_plan(db, redis, user_id, now, complete=None, llm=None)`: when `complete is None`, try `_plan_with_tools(...) -> Optional[TradePlan]` first; on `None` fall through to the existing loop. `llm` is passed to `run_with_tools` (tests).
- Seed = `_context(...)` with candidates' `news` lists removed (the model fetches news itself) rendered through `game_plan_tools.md`; grounding facts = runner `facts` + the parsed seed values.
- `numbers_in` change: a string that is not itself a number contributes every number found inside it (same `_NUMBER` regex).

- [ ] Step 1: failing tests (`FakeRedis`, mongomock, scripted LLM): `test_builder_uses_tools_then_validates_and_stores` (script: `news` call for AXISBANK, then JSON reply → stored `pre_open`, `tool_trace` names `news`, plan budget counter = 2), `test_unsupported_rationale_lines_are_dropped` (reply rationale `["Crude at $150 hits OMCs.", "Regime neutral at +0.10."]` with regime score 0.1 in seed → only the second line kept), `test_invalid_tool_reply_falls_back_to_single_call` (the tool loop's final reply and its repair are not JSON → runner output None → single-call path runs with a stubbed `_llm` and its plan is stored), `test_tools_off_uses_single_call` (`AI_TOOLS_ENABLED=False`), `test_numbers_in_reads_numbers_inside_text` (grounding).
- [ ] Step 2–4: FAIL → implement → PASS.
- [ ] Step 5: commit `feat(plan): pre-open plan fetches its facts through tools [skip ci]`

---

### Task 2: Revision on tools

**Files:** Modify `backend/plan/revise.py`; Create `backend/prompts/game_plan_revision_tools.md`; modify `backend/tests/test_prompts.py`; Test `backend/tests/test_plan_revise_tools.py`.

**Interfaces — Produces:** `revise_plan(db, redis, user_id, plan, reasons, now, complete=None, llm=None)`: when `complete is None`, tool path first (seed = current revision placeholders; tools `news`, `price_summary`, `positions`; plan budget), reply → `PlanReply` → `validate(..., trigger=reasons[0][0], ...)` → grounded rationale → scope-union → save → `_tell`; `None` → existing single-call path.

- [ ] Step 1: failing tests: `test_revision_uses_tools_and_keeps_exits` (scripted: `news` then JSON with an exit → version 2 with the exit), `test_revision_without_positions_still_proceeds`.
- [ ] Step 2–4: FAIL → implement → PASS (full suite).
- [ ] Step 5: commit `feat(plan): plan revisions fetch their facts through tools [skip ci]`

---

### Task 3: Docs, deploy, verify

- [ ] ROADMAP (16.2 done), ARCHITECTURE (plan paragraph: tools first, single-call fallback).
- [ ] Full suite; commit + push; rebuild `backend ingest`.
- [ ] Verify on prod: run `build_plan` for the real auto-intraday user dated today with the real model; log shows `ai game_plan: N round(s), tools [...]`; stored doc trigger `pre_open` with grounded rationale; delete the doc and Redis key afterwards.
