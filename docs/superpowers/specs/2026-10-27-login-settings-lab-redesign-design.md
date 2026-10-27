# Login, Settings, Lab redesign: glow login, leftovers out

Date: 2026-10-27. Status: approved in chat. Sub-project 7 (last) of the whole-app UX overhaul
(identity: `2026-10-27-visual-identity-design.md`). Frontend only, no backend change.
Settings and Lab layouts were redesigned earlier the same day; only styling leftovers remain.

## Intent

- Owner: Login's card on the Hero glow surface with a big wordmark; Settings, Lab, Profile leftovers fixed.
- Owner rule: every feature, control, link and piece of data stays; simplest result.

## 1. Login (`frontend/src/pages/Login.jsx`)

- `<Card className="w-full max-w-sm !p-6">` -> `<div className="w-full max-w-sm rounded-[28px] border border-[var(--border)] p-6" style={{ background: 'var(--glow)' }}>`
  (drop the `Card` import if unused).
- Wordmark `h1`: `text-2xl font-bold` -> `text-[44px] font-extrabold tracking-[-0.04em] leading-none`.
- Error `p`: `border border-[var(--loss)] bg-[var(--loss-wash)]` -> `rounded-[12px] bg-[var(--loss-soft)]`; keeps `role="alert"`.
- Pitch, Paper badge, broker line, `GoogleLogin` (theme switch), broker code, beta footer unchanged.

## 2. Leftovers (classes only)

- `rounded-[16px]` -> `rounded-[20px]`: `components/settings/Group.jsx`, `pages/SettingsHome.jsx` profile card,
  `pages/Handbook.jsx` article, `pages/OptionChain.jsx` section.
- `-wash` -> `-soft`: `components/settings/Models.jsx` test pills (~253-254), `components/settings/Panel.jsx` `Stamp`.
- `components/settings/Notifications.jsx` toggle: drop `shadow-sm`.
- `pages/LabRuns.jsx` and `pages/LabForward.jsx` "Open Strategies" links: `text-[var(--surface)]` on accent ->
  `text-[var(--accent-ink)]`.
- Unchanged on purpose: `pages/Profile.jsx` `bg-[var(--text)] text-[var(--surface)]` chips (dark fill, not accent);
  SettingsHome Appearance radio `rounded-[8px]` inside its 12 px track; `doc-meta` uses.
- `docs/wiki/frontend.md`: Login line (glow card) and `verified_at`.

## 3. Tests and checks

- `pages/Login.test.js` (extend): `var(--glow)`, `rounded-[28px]`, `text-[44px]`, error `--loss-soft` with
  `role="alert"`, no `-wash)`; `GoogleLogin`, `Paper until proven`, `Not investment advice` still present.
- Source test over the leftover files: no `rounded-[16px]`, `-wash)`, `shadow-sm`, `bg-[var(--accent)] text-[var(--surface)]`.
- `npm test && npm run lint && npm run build` green.
- Playwright 390x844, both themes, mocked API: `/login` plain, with error, with broker code (`?code=`);
  `/settings`; `/settings/lab`; LabRuns empty; `/lab/handbook` (or its route); OptionChain; `/settings/ai`.
  `scrollWidth <= 390`.
- Deploy Direct (`[skip ci]`), frontend only.

## Out of scope

Backend; `doc-meta`; layouts of Settings/Lab (done earlier); the Watchlist non-INR `₹` bug (separate fix).
