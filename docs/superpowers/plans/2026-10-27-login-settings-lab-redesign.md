# Login, Settings, Lab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Login on the glow surface with a big wordmark; styling leftovers out of Settings, Lab and their components.

**Architecture:** Class-only edits; Login swaps its `Card` for a glow `div`.

**Tech Stack:** React 19, Vite, Tailwind v4, `node --test`, Playwright (scratch only).

**Spec:** `docs/superpowers/specs/2026-10-27-login-settings-lab-redesign-design.md`

## Global Constraints

- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Frontend only; no new npm dependency.
- Text on an `--accent` fill uses `--accent-ink`. No `rounded-[16px]`, `-wash)`, `shadow-sm` in touched files.
- `cd frontend && npm test && npm run lint && npm run build` green before every commit.
- Commit subjects end `[skip ci]`; body ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.

## Review Focus

- Login in light theme: `--glow` gradient behind the Google button and text stays readable (render check).
- Login with `?code=` (broker return): broker code line still shows, `select-all` kept.
- Google button theme still follows `theme` (`filled_black` dark, `outline` light).
- Models test result pill (success/failure) still distinguishable by text, not colour only.
- Group radius change does not clip `ListRow` focus rings (render check).

---

### Task 1: Glow Login

**Files:**
- Modify: `frontend/src/pages/Login.jsx:~36-77`, `frontend/src/pages/Login.test.js`

- [ ] **Step 1: Failing tests** in `Login.test.js`: contains `var(--glow)`, `rounded-[28px]`, `text-[44px]`, `font-extrabold`; error has `role="alert"` and `--loss-soft`, no `-wash)`; still contains `GoogleLogin`, `filled_black`, `Paper until proven`, `Not investment advice`, `select-all`.
- [ ] **Step 2: Run** `cd frontend && node --test src/pages/Login.test.js`. Expected FAIL.
- [ ] **Step 3: Implement** per spec §1.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 5: Commit** `feat(login): glow card and big wordmark [skip ci]`.

### Task 2: Settings and Lab leftovers

**Files:**
- Modify: `frontend/src/components/settings/{Group,Models,Panel,Notifications}.jsx`, `frontend/src/pages/{SettingsHome,Handbook,OptionChain,LabRuns,LabForward}.jsx` (classes only, lines per spec §2)
- Test: `frontend/src/components/settings/settingsIdentity.test.js` (create)

- [ ] **Step 1: Failing source test** over those nine files: no `rounded-[16px]`, no `-wash)`, no `shadow-sm`, no `bg-[var(--accent)] text-[var(--surface)]`; LabRuns and LabForward contain `text-[var(--accent-ink)]`; `Profile.jsx` not included.
- [ ] **Step 2: Run**, expect FAIL.
- [ ] **Step 3: Implement** per spec §2.
- [ ] **Step 4: Run** `npm test && npm run lint && npm run build`. PASS (update existing tests that pin the old classes).
- [ ] **Step 5: Commit** `style(settings): Settings and Lab leftovers on the identity [skip ci]`.

### Task 3: Wiki and render check

**Files:**
- Modify: `docs/wiki/frontend.md` (Login line; `verified_at`)
- Scratch: `/tmp/claude-1001/-home-ubuntu/43fc11bd-c4e1-48a1-b056-774e9821ae4b/scratchpad/pw/settings-shots.mjs`, shots in `pw/settings/`

- [ ] **Step 1: Wiki** update; `verified_at` = base commit.
- [ ] **Step 2: Render** 390x844, both themes: `/login` plain, with an error (mock the Google flow failing or set state via a failing `/auth` mock), with `?code=abc`; `/settings`; `/settings/lab`; LabRuns empty; Handbook; OptionChain; `/settings/ai`. Assert `scrollWidth <= 390`. Read every PNG. Fix breaks only in Task 1-2 files, re-shoot.
- [ ] **Step 3: Run** `npm test && npm run lint && npm run build`. PASS.
- [ ] **Step 4: Commit** `docs(settings): wiki for the glow login [skip ci]` (plus `fix(...): ... [skip ci]` if code changed).

## Waves

1. Tasks 1 and 2 in parallel (disjoint).
2. Task 3, final review, push (Direct).
