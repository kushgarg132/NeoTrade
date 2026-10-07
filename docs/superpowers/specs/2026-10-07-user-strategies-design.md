# Your own strategies: compose a block strategy, the same gates decide

User-approved design, 2026-10-07. Extends the strategy builder
(`2026-10-07-strategy-builder-design.md`): same block vocabulary, validator, interpreter and
checks, now reachable from a form, owned by the user who made it.

## Intent

Today only the AI's weekly builder can create a strategy. The owner wants any user to
compose one from the same blocks on Practice › Strategies, see it backtested through the
same checks, and, if it passes, have it trade on that user's paper book. A user's strategy
is private: it never loads, shows or trades for anyone else.

Success: a user submits a strategy from the form and, within minutes, sees it Active or
Rejected with the reason and its year and last-90-day results; a passing one trades in that
user's next intraday paper run and nowhere else.

### Decisions (from the brainstorm)

| Question | Decision |
|---|---|
| Who may add | **Any user, private** to that user. |
| Storage | The existing `built_strategies` collection gains `owner_id` (`None` = the AI's global drafts). |
| Checks | Unchanged: gate, last 90 days net-positive, Deflated Sharpe ≥ 0.95. |
| Overfitting count | **Per owner**: a user's own tries raise only their own bar. |
| Path to live | Unchanged: the user's paper record plus their own live switch. |

### Invariants

1. Every per-account record carries `user_id`; a user's strategy is visible and runnable only
   for its owner. The AI's drafts (`owner_id = None`) stay global.
2. No model output and no user input is executed as code: a spec is data, cleaned by
   `builder/validate.py::validate_spec`, run by `strategies/built.py::BlockStrategy`.
3. `composite.py`, `AI_CAP`, `RULE_FLOOR`, kill switch, fence, backtest gate and paper gate
   apply unchanged.
4. `backend/strategies/` stays I/O-free and wall-clock-free.

## 1. Scoping (one choke point)

- `built_strategies` docs gain `owner_id: str | None`. Existing docs have none and read as
  `None` (global).
- `strategies/built.py::active()` keeps every active doc, global and per-user;
  `registry.build_default_strategies(..., user_id: str | None = None)` loads the global
  ones plus those whose `owner_id == user_id`. `user_id=None` loads global ones only.
- Callers that act for a user pass `user_id`: `routers/trading.py::launch_run`,
  `learning/library.py::catalog` (and through it the game plan and chat library tool), the
  settings strategy list and promotion endpoints, the chat strategy-name tool and
  `plan/replay.py`. Callers without a user (the gate backtest of built-ins, the monthly
  re-tune) keep `user_id=None`: user strategies are not re-tuned (out of scope).
- `GET /strategies/built` and the chat `built_strategies` fact return the global drafts plus
  only the caller's own.
- Slugs stay globally unique (existing unique index), so gate rows keyed `built:<slug>` never
  collide across users.

## 2. Form (Practice › Strategies)

- A **New strategy** button opens a sheet: **Setup** (one block, then its parameters),
  **Filters** (0–3), **Long / Short**, **Stop** (ATR multiple or the setup bar), **Target**
  (R multiple), **Name** (becomes the slug through `slugify` and a uniqueness suffix) and a
  one-line **Thesis**.
- Parameter inputs, ranges and steps come from `GET /strategies/vocabulary`, rendered from
  `strategies/blocks/vocab.py`, so the form never drifts from the validator.
- A live preview shows `describe(spec)` via `POST /strategies/describe` (validate + describe,
  no storage).
- Phone width: one column, no horizontal scroll.

## 3. Submit and test

- `POST /strategies/built` (any logged-in user): `validate_spec(raw, existing)` where
  `existing` = the user's own specs (a duplicate of their own is refused; a duplicate of
  someone else's is allowed, since it is private). Refusal returns 422 with the reason.
- Limits: at most 3 submissions per user per IST day (Redis counter, as other per-user
  limits), at most one of the user's strategies `testing` at a time (409 "A strategy of yours
  is still being tested."), at most 5 active per owner (409 at submit when 5 are active:
  "Retire one first.").
- Stored as `status=testing`, `owner_id=user`, then `python -m backend.builder --test <slug>`
  is spawned (nice, own process, as the weekly job). That mode tests one draft, with no LLM
  call, under a per-slug Redis lock.
- History: the admin's Upstox year of 5-minute candles (the only source); sizing: the
  **owner's** `account_size`, `max_exposure`, `per_trade_cap`. No history source: the draft
  stays `testing` with verdict "waiting for market history" and the weekly job retries it.
- Pass needs the same three checks as AI drafts (`builder/draft.py::_test`). The Deflated
  Sharpe counts the owner's own tested drafts (`store.trial_sharpes(db, owner_id)`); the AI's
  count stays the AI's.
- Pass -> `active` for that owner; fail -> `rejected` with the first failing reason.

## 4. Results and actions

- Practice › Strategies shows a **Mine** section: each of the user's strategies with its
  description, thesis, a status chip (Testing / Active / Rejected / Retired), the verdict, and
  the year and last-90-day lines. While any is Testing the section refreshes every 10 s.
- **Retire** on the user's own active ones (`POST /strategies/built/{slug}/retire`, owner
  only) -> `retired`, never loaded again.
- **Re-test** on the user's own rejected ones (`POST /strategies/built/{slug}/retest`, owner
  only, same limits) -> `testing`; counts as a new trial.
- Active user strategies also appear in the regular strategy list with the **Built** badge
  plus "Yours", their gate result and paper record, and their live switch in Practice › Setup.

## 5. Error handling

- Validator refusal, limits and ownership failures are 4xx with a plain sentence.
- A spawn failure leaves the draft `testing`; the weekly job retries every waiting draft.
- A backtest failure leaves it `testing` with the error recorded in `verdict` for the owner
  to see.

## 6. Testing

- Scoping: user A's active strategy loads in A's `build_default_strategies(user_id=A)` and
  catalog, not in B's, not with `user_id=None`; global drafts load for both.
- API: submit validates and stores with `owner_id`; duplicate of own refused, of another's
  allowed; daily limit, one-testing and 5-active limits; retire/retest owner-only (404 for
  others); `/strategies/built` and the fact return global + own only.
- `--test <slug>` mode: tests one draft, makes no LLM call, sizes with the owner's prefs, and
  uses the owner's trial count.
- Frontend: the form builds the canonical spec shape from the vocabulary; `npm run build`.

## Out of scope

Editing a strategy in place; sharing strategies between users; re-tuning user strategies;
options blocks; AI drafting for individual users.
