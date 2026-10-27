# Visual identity: dark-first deep emerald ("Glow card")

Date: 2026-10-27. Status: approved in chat. Sub-project 1 of the whole-app UX overhaul.
Frontend only. Direction picked from three hosted mockups (A "Glow card"):
https://claude.ai/artifact/G2cjj66Jtqo5n21FH8mSSd

## Why

The owner says the app "feels very generic and AI made". It is the default SaaS kit: indigo
`#4338ca`, Archivo, white 16 px cards on grey, one card pattern everywhere. The owner chose a
premium-fintech feel (bold type, big hero numbers, one strong brand colour, tactile motion),
deep emerald as the brand, dark as the hero theme.

## The overhaul, in sub-projects (each gets its own spec, plan, build)

1. Identity (this spec): tokens, fonts, primitives, three signature components, header and nav, DESIGN.md, Home hero as proof.
2. Home. 3. Money (holdings, journal, tax). 4. Ideas + AI. 5. Market + Stock (+ index, sector, news).
6. Detail pages (idea, AI trade, round trip, strategy, weekly report). 7. Login, Settings, Lab.

## 1. Colour tokens (`frontend/src/index.css`)

Token names stay (`--bg`, `--surface`, `--surface-2`, `--border`, `--text`, `--text-muted`,
`--accent`, `--gain`, `--loss`, `--warn`, `--chart-*`, `--heat-*`) so every component follows.
New tokens: `--accent-ink` (text on an accent fill), `--glow` (the hero gradient), `--gain-soft`,
`--loss-soft` (chip fills).

| token | dark (hero) | light |
|---|---|---|
| `--bg` | #07100c | #f6f8f6 |
| `--surface` | #0d1914 | #ffffff |
| `--surface-2` | #12211a | #edf2ee |
| `--border` | #17271f | #dce5df |
| `--text` | #e9f3ee | #0f1a14 |
| `--text-muted` | #9dbcad | #4f6157 |
| `--accent` | #10b981 | #047857 |
| `--accent-ink` | #04140d | #ffffff |
| `--gain` | #3ddc97 | #0f7b4f |
| `--loss` | #ff6b6b | #c2281d |
| `--warn` | #f2b24a | #9a5b00 |
| `--gain-soft` / `--loss-soft` | gain / loss at 14% over `--surface` | gain / loss at 10% over `--surface` |
| `--glow` | `radial-gradient(120% 90% at 0% 0%, #0f5c3f 0%, #0b2a1f 55%, var(--bg) 100%)` | `radial-gradient(120% 90% at 0% 0%, #c9f0dd 0%, #e8f6ef 55%, var(--surface) 100%)` |

Rules: `--accent` (brand emerald) never colours a number; numbers use `--gain`/`--loss`/`--text`
and every gain or loss carries ▲/▼ or a sign. `--text` and `--text-muted` keep ≥ 4.5:1 on `--bg`,
`--surface` and `--surface-2` in both themes (checked by a test). Chart and heat tokens keep their
current values. The old alias names (`--paper`, `--ink`, `--rule`, `--stamp`) stay mapped.

Theme default: dark. `ThemeContext` returns the stored choice when there is one, otherwise
`'dark'` (no longer the OS setting).

## 2. Type

- Geist (Google Fonts, weights 400/500/600/700/800) replaces Archivo in the `@import` and
  `--font-sans`; fallback `ui-sans-serif, system-ui, sans-serif`. `index.html` comment naming
  Archivo updated.
- Scale tokens `--fs-12/13/15/17/22/28/44`; body 15 px. Nothing functional below 12 px.
- Hero number: 44 px, weight 800, letter-spacing -0.04em, line-height 1, tabular figures.
- Section labels: 13 px semibold `--text-muted`, sentence case (no uppercase eyebrows).
- Page titles (`PageHeader`): 22 px bold, letter-spacing -0.02em.

## 3. Shape, primitives and signature components (`frontend/src/components/ui/`)

Radius: 12 controls, 20 cards, 28 hero, 999 pills. 1 px tinted borders; no box shadows in dark.

Restyled (same props, so no caller changes): `Card` (radius 20, `--surface`, `--border`),
`Tile`, `Stat`, `ListRow` (press state), `Badge` (pill), `Button` (primary = `--accent` fill with
`--accent-ink`, radius 12, 44 px), `Tabs` (segmented pill, active `--surface` on `--surface-2`),
`PageHeader`, `Empty`, `Skeleton` (shimmer in `--surface-2`), `ErrorLine`.

New:
- `Hero({ label, value, change, children })`: radius 28, `background: var(--glow)`, `--border`;
  `label` 12 px muted, `value` hero number, `change` slot (a `DeltaChip`), `children` footer row.
  At most one per page; used by Home this sub-project.
- `DeltaChip({ value, pct, suffix })`: pill, `--gain-soft`/`--loss-soft` fill, `--gain`/`--loss`
  text, ▲/▼ prefix, money via `format.js`, carries `private` for money. `value` 0 renders neutral
  (`--surface-2`, no arrow).
- `GradeTile({ grade })`: 40 px, radius 12, A = `--accent` fill + `--accent-ink`, B = `--surface-2`
  + `--text`, C = transparent + `--border` + `--text-muted`; `aria-label="Grade A"`.

Chrome: `layout/Header` (logo "NeoTrade" 18 px 700, `MarketDot` unchanged in logic),
`BottomTabs` and `SideRail` (active item `--accent` icon + label, inactive `--text-muted`,
`--surface` bar with `--border` top line).

## 4. Motion (CSS only, no new dependency)

- Press: `.tap:active { transform: scale(.98) }` with 120 ms ease-out; applied by `ListRow`,
  `Button`, `Card` when it links.
- Hero count-up: `Hero` animates the numeric value from 0 over 600 ms ease-out on first mount
  only (not on refresh), via `requestAnimationFrame`; the final text is the formatted value.
- Tab panels fade in over 150 ms.
- All of it off under `@media (prefers-reduced-motion: reduce)` (count-up shows the final value).

## 5. Scope, docs, checks

- Home's top value block becomes `Hero` + `DeltaChip`; the rest of Home waits for sub-project 2.
- `DESIGN.md` rewritten for this identity (tokens table, type, shape, the three components,
  motion, rules). `docs/wiki/frontend.md` Design tokens section and `verified_at` updated.
- Tests: contrast test over the token table for both themes (text and text-muted ≥ 4.5:1 on bg,
  surface, surface-2; gain/loss ≥ 4.5:1 on surface); `ThemeContext` default dark; `DeltaChip`
  sign/arrow/neutral; `GradeTile` labels; source test that `--font-sans` names Geist.
- Render check: Playwright with mocked API at 390 px, both themes, screenshots of Home, Money,
  Ideas, AI, Market, Settings; no horizontal scroll. Owner reviews screenshots.
- Leftover old-kit styles (20 files with `doc-meta`, dashed borders, old aliases) are listed in
  the plan for sub-projects 2-7, not fixed here.

## Out of scope

Page layouts and copy (sub-projects 2-7), new features, charts restyle beyond tokens, a motion
library.
