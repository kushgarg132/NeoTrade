# Alert Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every NeoTrade Telegram alert through one `alert()` that sends four kinds at once as a card with buttons, queues the rest for the two daily digests, honours per-kind mutes, and logs every alert.

**Architecture:** New `backend/alerts.py` owns the kind table, the card renderer, the `alerts` collection (log + queue), `drain`/`requeue` for the digests, and the Sell/Open button builders. Every current sender switches to it; `suggestions/notify.notify` and `IdeaText` are deleted. A new `sell` Telegram callback turns the exit card's Sell tap into the existing chat-action Confirm/Cancel card.

**Tech Stack:** FastAPI, Motor/MongoDB (tests: `mongomock_motor`), aiogram via `backend/guardrails/telegram.py`, React 19 + vitest.

**Spec:** `docs/superpowers/specs/2026-11-01-alert-router-design.md`

## Global Constraints

- Instant kinds: `exit`, `money`, `news_breaking`, `action`. Batched kinds: `ideas`, `news`, `learning`, `review`, `autopilot_refused`, `stale_ideas`.
- Icons: exit 🔴, money 🤖, news_breaking 📰, action ⚠️. Card = icon + `<b>title</b>` + at most 3 lines, all data `html.escape`d.
- Digest block heading "Since last update"; at most 5 items a kind, then "…and N more".
- `alerts` collection fields `{user_id, kind, title, lines, symbol, link, state, created_at, digested_at}`; `state ∈ queued|digested|sent|muted|failed`; TTL 30 days on `created_at`.
- Prefs defaults `alert_mute: {}`, `breaking_news_min: 7` (int 5–9).
- New setting `APP_URL` (`https://neotrade-trading.vercel.app` in the deploy `.env`); unset → no URL buttons.
- `ideas` and `stale_ideas` reach admins only.
- No AI order to the `mine` account: the Sell button only proposes; the user's Confirm tap executes through `chat/actions.confirm`.
- Text builders keep returning `str` but drop closing instruction prose ("Decide under …", "Sell in your broker app …") and leading emoji; callers pass them through `alerts.split(text) -> (title, lines)`. (Deliberate simplification of the spec's "(title, lines)" wording: same result, one helper instead of ~10 signature changes.)
- Each code change updates its handbook/wiki section and `verified_at` in the same commit (`.claude/CLAUDE.md`).
- Tests: `cd backend && python -m pytest`; frontend `npx vitest run` and `npm run build`.

## Review Focus

1. Telegram down or chat unlinked when an instant alert fires → caller must not raise; `_level_pass` must still free its once-per-level keys (alert returns `False`).
2. Digest send fails after `drain` claimed rows → rows back to `queued`, sent next digest, never lost or doubled.
3. Two digest workers draining at once → each row claimed once (claim by `update_many` on `state="queued"` with ids read first; only ids whose update matched are rendered).
4. A muted batched kind already in the queue when the user mutes it → not shown in the digest.
5. Sell tap after the holding was already sold → existing `_refuse_oversell` reply, no card.

Each has a test in the owning task (Task 1: 1, 3, 4; Task 5: 2; Task 4: 5).

---

## Wave plan

- Wave 1: Task 1.
- Wave 2 (parallel, disjoint files): Tasks 2, 3, 4, 5, 6.
- Wave 3: Task 7.

### Task 1: Router core, collection, prefs, setting

**Files:**
- Create: `backend/alerts.py`, `backend/tests/test_alerts.py`
- Modify: `backend/guardrails/telegram.py::alert` (add `buttons`), `backend/server.py` (index, next to `picks_dismissed`), `backend/configs/settings.py` (`APP_URL: Optional[str] = None`), `backend/prefs.py` defaults, `backend/routers/settings.py::PreferencesPatch`, `backend/tests/test_settings_router.py`, `docs/wiki/platform.md`

**Interfaces (Produces):**
- `INSTANT: frozenset[str]`, `BATCHED: frozenset[str]`, `KINDS = INSTANT | BATCHED`, `ICONS: dict[str, str]`, `ORDER: tuple[str, ...]` (digest kind order: ideas, stale_ideas, news, learning, review, autopilot_refused)
- `split(text: str) -> tuple[str, list[str]]` — first non-empty line is title, rest are lines
- `card(kind: str, title: str, lines: Sequence[str]) -> str`
- `async alert(db, user_id, kind, title, lines=(), *, symbol=None, link=None, buttons=None) -> bool`
- `async drain(db, user_id, now: datetime) -> tuple[str, list]` → (HTML block or `""`, claimed ids)
- `async requeue(db, ids: list) -> None`
- `open_button(path: str, text: str = "Open") -> list[dict]` → `[]` when `APP_URL` unset, else `[{"text": text, "url": APP_URL + path}]`
- `sell_buttons(symbol: str, quantity: int, path: str) -> list[list[dict]]` → `[[{"text": f"Sell ×{quantity}", "callback_data": Tap(command="sell", id=f"{symbol}|{quantity}").pack()}, *open_button(path)]]`. Import `Tap` lazily from `backend.guardrails.telegram_bot`.
- `telegram.alert(db, user_id, text, html=False, buttons=None) -> bool`: passes `{"inline_keyboard": buttons}` as `reply_markup` when given.

- [ ] **Step 1: Write failing tests in `backend/tests/test_alerts.py`** (mongomock DB, monkeypatch `backend.guardrails.telegram.alert` with a recorder returning `True`; seed `users` with `{"id": "boss", "role": "admin"}` and `{"id": "bob"}`)

```python
async def test_unknown_kind_raises(): pytest.raises(ValueError) on alert(db, "boss", "nope", "x")
async def test_instant_sends_card_and_logs_sent():
    assert await alerts.alert(db, "boss", "exit", "Sell · TCS", ["Stop hit"]) is True
    assert sent[0]["text"] == "🔴 <b>Sell · TCS</b>\nStop hit" and sent[0]["html"] is True
    assert (await db["alerts"].find_one())["state"] == "sent"
async def test_card_escapes_and_caps_three_lines(): card("exit", "A<B", ["1","2","3","4"]) == "🔴 <b>A&lt;B</b>\n1\n2\n3"
async def test_failed_send_logs_failed_and_returns_false()   # recorder returns False
async def test_telegram_raising_is_swallowed()                # recorder raises → returns False, state "failed"
async def test_log_write_failure_does_not_block_send()        # db["alerts"].insert_one patched to raise; still sent, returns True
async def test_muted_kind_logs_muted_and_does_not_send()      # user_prefs {"user_id":"boss","alert_mute":{"exit":True}}
async def test_ideas_admin_only(): alert(db,"bob","ideas","x") is False and nothing logged
async def test_batched_kind_queues(): alert(db,"boss","news","x") is True, row state "queued", no send
async def test_drain_groups_caps_and_claims():  # 7 "news" + 1 "learning" queued
    block, ids = await alerts.drain(db, "boss", NOW)
    assert block.startswith("<b>Since last update</b>") and "…and 2 more" in block and len(ids) == 8
    assert await db["alerts"].count_documents({"state": "queued"}) == 0
    assert (await alerts.drain(db, "boss", NOW)) == ("", [])
async def test_drain_skips_kind_muted_after_queueing()        # queue "news", then mute news → block "", row stays queued
async def test_requeue_restores(): requeue(ids) → state "queued", digested_at None
async def test_sell_buttons_without_app_url_has_only_sell()   # settings.APP_URL None
async def test_split(): split("Title\nA\n\nB") == ("Title", ["A", "B"])
```

Plus in `test_settings_router.py`: PUT `alert_mute={"exit": True}` saved; `{"bogus": True}` → 422; `breaking_news_min=0` and `11` → 422.

- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_alerts.py tests/test_settings_router.py -q` — expect failures (`ModuleNotFoundError: backend.alerts`).

- [ ] **Step 3: Implement.** In `alert()`: validate kind → admin gate for `ideas`/`stale_ideas` (`suggestions.notify.is_admin`) → mute check from `PrefsStore(db).get(user_id)["alert_mute"]` → instant: send in `try/except Exception` (log warning), then best-effort `insert_one` of the log row; batched: `insert_one` with `state="queued"`. `drain()`: read queued rows for the user (sorted `created_at`), drop muted kinds, then `update_many({"_id": {"$in": ids}, "state": "queued"}, {"$set": {"state": "digested", "digested_at": now}})` and render only rows re-read with `state="digested"` and `digested_at == now` (race guard). Each item renders as `• {title}`; kinds in `ORDER`, a `<b>{label}</b>` line per kind (labels: Ideas, Expiring ideas, News, Learning, Your week, Autopilot). `stale_ideas` is added in Task 5, not here. Prefs: add defaults; `PreferencesPatch` gets `alert_mute: Optional[dict[str, bool]]` with a validator rejecting keys not in `alerts.KINDS`, and `breaking_news_min: Optional[int] = Field(default=None, ge=1, le=10)`. Index: `await d["alerts"].create_index("created_at", expireAfterSeconds=30 * 86400)` and `create_index([("user_id", 1), ("state", 1)])`.

- [ ] **Step 4: Run** the same command — expect PASS. Then full `python -m pytest -q` in background.

- [ ] **Step 5: Docs + commit.** Add an "Alerts" section to `docs/wiki/platform.md` (router, kinds, collection), bump `verified_at`.

```bash
git add backend/alerts.py backend/tests/test_alerts.py backend/guardrails/telegram.py backend/server.py backend/configs/settings.py backend/prefs.py backend/routers/settings.py backend/tests/test_settings_router.py docs/wiki/platform.md
git commit -m "feat(alerts): one router with instant cards, digest queue, mutes and a log"
```

### Task 2: Move `notify()` callers onto the router

**Files:**
- Modify: `backend/scheduler.py` (ideas `:109`, pause `:394`, weekly learning `:396`, mirror `:433`), `backend/engine/autorun.py` (levels `:313`, exits `:337`, factor paper `:366`, morning ideas `:386`, autopilot summary `:490`, login `:528`), `backend/datalayer/reactor.py` (`_deliver`, `:221`), `backend/builder/draft.py:394`, `backend/suggestions/notify.py` (builders only), `backend/mine/actions.py::levels_text`, `backend/learning/report.py::pause_text`, related tests (`test_autorun.py`, `test_datalayer_reactor.py`, any test asserting old builder text), `docs/wiki/data-ai-jobs.md`
- Do NOT touch `portfolio/digest.py` or `reports/weekly.py` (Task 5) and do not delete `notify()` (Task 7).

**Interfaces:** Consumes Task 1 `alert`, `split`, `sell_buttons`, `open_button`.

Mapping (kind, buttons):
- levels → one `exit` alert **per level** (title `Sell · {symbol}` for stop_hit, `Target · {symbol}` for target_hit; line = the level's `detail`; `sell_buttons(a["symbol"], a["ticket"]["quantity"], f"/mine/stock/{symbol}")`). `_level_pass` frees the Redis key of every alert whose `alert()` returned `False`.
- exits → one `exit` alert per closed idea: title `Sell · {symbol}`, line `"{reason} at ₹price · bought ₹entry · gross ₹pnl"`, `sell_buttons(symbol, quantity, f"/mine/stock/{symbol}")`.
- autopilot summary `:490` → `money` when `bought`, else `autopilot_refused`; buttons `STOP_BUTTON` row + `open_button("/settings/autopilot")` for `money`.
- login `:528` → `action`, `buttons=[open_button("/settings")]` (skip the row if empty).
- ideas (`:109`, `:386`, `reactor:221`) → `ideas`; pause/weekly learning/factor paper/builder → `learning`; mirror → `review`.
- reactor `_deliver`: `news_breaking` if any hit's `target` is in the user's held set and `impact >= prefs["breaking_news_min"]`, else `news`; `symbol` = that hit's target; buttons `[[*open_button(f"/stock/{symbol}", "Open stock"), {"text": "Article", "url": item["url"]}]]` when url present. `_audience` already returns held sets; pass held into `_deliver`.

- [ ] **Step 1: Write failing tests.**
  - `test_datalayer_reactor.py::test_held_high_impact_is_breaking` (held TCS, impact 8, default prefs → alert kind `news_breaking`) and `::test_watched_or_low_impact_is_news` (impact 6 held → `news`; impact 9 watched-only → `news`). Monkeypatch `backend.alerts.alert` with a recorder.
  - `test_autorun.py::test_level_pass_one_exit_alert_per_level_with_sell_button` and `::test_level_pass_frees_keys_when_unsent` (recorder returns `False` → Redis `mine:alert:*` keys deleted).
- [ ] **Step 2: Run** `python -m pytest tests/test_datalayer_reactor.py tests/test_autorun.py -q` — expect FAIL.
- [ ] **Step 3: Implement** the mapping above; strip instruction prose and leading emoji from `proposals_text`, `exits_text`, `levels_text`, `pause_text`, `reactor.alert_text`; update tests asserting the old strings.
- [ ] **Step 4: Run** full `python -m pytest -q` — expect PASS.
- [ ] **Step 5: Docs + commit** (`docs/wiki/data-ai-jobs.md` notify call sites → alerts kinds; handbook `frontend/src/handbook/ai-and-news.md` news-alert paragraph):

```bash
git commit -m "feat(alerts): engine, news and learning alerts go through the router"
```

### Task 3: Move direct Telegram senders onto the router

**Files:**
- Modify: `backend/guardrails/monitor.py::_alert` (signature becomes `_alert(db, user_id, event)`; callers pass `db`), `backend/system/data_quality.py::_send_admins` (calls `alert(db, admin_id, "action", ...)` per admin), `backend/plan/notify.py::notify_plan`, `backend/autopilot/service.py::_notify` and `_record`, tests `test_data_quality.py`, `test_plan_notify.py`, guardrail monitor tests.

**Interfaces:** Consumes Task 1 `alert`, `split`, `open_button`. `STOP_BUTTON` stays in `autopilot/service.py`.

Mapping: guardrail breach → `money`, title `event["title"]`, line `event["detail"]`, buttons `[open_button("/settings/guardrails")]` if non-empty (WebSocket publish unchanged). Data quality → `action`, `split(text)`. Plan → `money`, `split(plan_text(doc))`, `buttons=STOP_BUTTON`. Autopilot `_record`: `FILLED` → `money` with `STOP_BUTTON`; refused → `autopilot_refused`. `_notify` keeps its signature and returns `alert(...)`'s bool.

- [ ] **Step 1: Write failing tests:** `test_plan_notify.py::test_plan_goes_out_as_money_card_with_stop_button`; `test_data_quality.py::test_admin_alert_is_action_kind`; autopilot `test_refused_order_is_queued_not_sent` (row in `alerts` with `state="queued"`, kind `autopilot_refused`).
- [ ] **Step 2: Run** those files — expect FAIL.
- [ ] **Step 3: Implement** the mapping; drop the now-unused `GuardrailStore`/`telegram` imports in these modules.
- [ ] **Step 4: Run** full `python -m pytest -q` — expect PASS.
- [ ] **Step 5: Commit** `feat(alerts): guardrail, data-quality, plan and autopilot alerts use the router` (wiki `platform.md` guardrails section if it cites `telegram.send`).

### Task 4: Sell tap → order card

**Files:**
- Modify: `backend/guardrails/telegram_bot.py::_callback` (new `sell` branch), `Tap` docstring; `backend/tests/test_telegram_bot.py`

**Interfaces:** Consumes Task 1 callback data `nt:sell:{symbol}|{quantity}`. Uses existing `backend.chat.actions.action_tools(db, redis, user_id, message)` (tool name `propose_order`), `CARD_PREFIX`, and this module's `_buttons(action)`.

- [ ] **Step 1: Write failing tests** in `test_telegram_bot.py`:
  - `test_sell_tap_sends_confirm_card`: callback data `Tap(command="sell", id="TCS|10").pack()`, `propose_order` stubbed to return `CARD_PREFIX + json.dumps({"id": "a1", "summary": "Sell 10 TCS"})` → `telegram.send_buttons` called with `"Sell 10 TCS"` and `_buttons({"id": "a1"})`; `answer_callback` called.
  - `test_sell_tap_refusal_is_answered_not_carded`: tool returns `"You hold 0 TCS"` → `answer_callback` with that text, no `send_buttons`.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot.py -q` — expect FAIL.
- [ ] **Step 3: Implement** the branch: parse `symbol, qty = action_id.rsplit("|", 1)`; `tools = {t.name: t for t in action_tools(db, redis, user_id, f"Sell {qty} {symbol}")}`; `out = await tools["propose_order"].coroutine(symbol=symbol, side="SELL", quantity=int(qty), product="CNC", account="mine")`; card or `answer_callback(out[:180])`. Must sit before the `command not in {"confirm", ...}` early return.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** `feat(alerts): Sell button on exit alerts opens the confirm card`.

### Task 5: Digests drain the queue, add stale ideas and buttons

**Files:**
- Modify: `backend/portfolio/digest.py` (`premarket_text`, `postclose_text`, `premarket_for`, `postclose_for`, `send_premarket`, `send_postclose`), `backend/alerts.py::drain` (stale ideas), `backend/reports/weekly.py::send` (switch `notify` → `telegram.alert(..., html=True)`), `backend/tests/test_portfolio_digest.py`, `backend/tests/test_alerts.py`, handbook page describing the digests.

**Interfaces:** Consumes Task 1 `drain`, `requeue`, `open_button`. `premarket_text(..., since: str = "")` and `postclose_text(..., since: str = "")` append `since` as the last block when non-empty. `send_*` build `buttons = [[*open_button("/ideas", "Review ideas"), *open_button("/", "Open Today")]]` (row omitted when empty) and send via `telegram.alert(db, user_id, text, html=True, buttons=...)`.

Stale ideas in `drain` (admins only, unless `alert_mute["stale_ideas"]`): count `suggestions` with `user_id`, `status="PENDING"`, `mode="LONGTERM"`; `M` = those with `expires_at` before the next digest (pre-market caller: today 15:30 IST; post-close caller: next trading day 08:45 IST — `drain` takes `until: datetime` for this). Line `"{N} pending, {M} expire before {close|the open}"` under the Ideas heading; pre-market's existing ideas line is replaced by it. `drain` signature becomes `drain(db, user_id, now, until=None)`.

- [ ] **Step 1: Write failing tests:**
  - `test_portfolio_digest.py::test_premarket_includes_since_block` and `::test_failed_send_requeues_drained_rows` (`telegram.alert` returns `False` → rows `queued` again; for pre-market also Redis key released as today).
  - `test_alerts.py::test_drain_stale_ideas_line` (3 pending, 1 expiring before `until` → `"3 pending, 1 expire before"` in block) and `::test_drain_stale_ideas_admin_only`.
- [ ] **Step 2: Run** those files — expect FAIL.
- [ ] **Step 3: Implement**; in `send_*` call `drain` before building text and `requeue(ids)` in the existing `except`/failed-send path (treat a `False` return from `telegram.alert` as failure).
- [ ] **Step 4: Run** full `python -m pytest -q` — expect PASS.
- [ ] **Step 5: Commit** `feat(alerts): digests carry everything queued since the last one`.

### Task 6: Settings UI

**Files:**
- Modify: `frontend/src/components/settings/Notifications.jsx`, `frontend/src/components/settings/Notifications.test.js`

**Interfaces:** Consumes `GET/PUT endpoints.settings.preferences` fields `alert_mute` (object kind→bool) and `breaking_news_min` (5–9).

Copy (exact): group "Instant" — Exit and sell signals (`exit`), Money moved (`money`), Breaking news on holdings (`news_breaking`), Needs your action (`action`); group "In the digest" — New ideas (`ideas`), Expiring ideas (`stale_ideas`), Other news (`news`), Strategy learning (`learning`), Weekly review (`review`), Autopilot refusals (`autopilot_refused`). A toggle on = not muted. Threshold control label "Breaking news from impact", options 5–9 shown as "5/10" … "9/10", via the existing `Segmented` component. Each change PUTs only the changed field, reverts and shows the existing note on error.

- [ ] **Step 1: Write failing tests:** toggling "Other news" off PUTs `{ alert_mute: { news: true } }` (merged with existing mutes); picking "8/10" PUTs `{ breaking_news_min: 8 }`; a failed PUT reverts the toggle.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/components/settings/Notifications.test.js` — expect FAIL.
- [ ] **Step 3: Implement** with existing settings components (look at sibling files in `components/settings/` for the toggle row; reuse, do not add a new one).
- [ ] **Step 4: Run** vitest file and `npm run build` (background) — expect PASS.
- [ ] **Step 5: Commit** `feat(settings): per-kind alert mutes and breaking-news threshold`.

### Task 7: Delete `notify()`, final sweep

**Files:**
- Modify: `backend/suggestions/notify.py` (remove `notify`, `IdeaText`), any remaining importer, `docs/wiki/INDEX.md` if it lists notify.

- [ ] **Step 1:** `grep -rn "notify import notify\|IdeaText\|telegram.send(" backend --include=*.py | grep -v tests` — expected: only `telegram_bot.py` chat replies and `routers/guardrails.py` link reply remain.
- [ ] **Step 2:** Delete `notify`/`IdeaText`; fix leftovers.
- [ ] **Step 3:** Run `python -m pytest -q`, `npx vitest run`, `npm run build` concurrently; `python3 docs/wiki/stale.py` reports no stale page for touched files.
- [ ] **Step 4: Commit** `refactor(alerts): remove notify(); the router is the only alert path`.
- [ ] **Step 5: Deploy note.** Add `APP_URL=https://neotrade-trading.vercel.app` to `/home/ubuntu/deploys/NeoTrade/.env` before the backend rebuild; ask deploy mode before the first push (host CLAUDE.md); per memory, a direct deploy also rebuilds the ingest and jobs services. After the first trading day: `db.alerts.aggregate([{$group: {_id: {kind: "$kind", state: "$state"}, n: {$sum: 1}}}])`.
