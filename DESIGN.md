# NeoTrade design system

A premium-fintech, dark-first money app: deep emerald brand, big bold numbers, one "glow" hero per page,
tactile press motion. Phone-first, one task per screen, plain words. Replaces the earlier indigo/Archivo kit
and, before it, the "contract note" look. The tokens are real, in `frontend/src/index.css`.
Spec: `docs/superpowers/specs/2026-10-27-visual-identity-design.md`.

## Tokens (dark is the hero theme)

Theme default is dark; a stored `light`/`dark` choice wins (the OS setting is ignored).

| token | dark | light | use |
|---|---|---|---|
| `--bg` | #0b0b0c | #f7f7f8 | page |
| `--surface` | #141416 | #ffffff | cards, header, tabs bar |
| `--surface-2` | #1c1c1f | #f0f0f2 | segmented track, pressed rows, skeleton |
| `--border` | #27272a | #e4e4e7 | hairlines |
| `--text` | #ededef | #18181b | primary text |
| `--text-muted` | #a1a1aa | #52525b | secondary text (>= 4.5:1 on bg, surface, surface-2) |
| `--accent` | #10b981 | #047857 | brand: links, active tab, primary button fill |
| `--accent-ink` | #04140d | #ffffff | text on an accent fill (>= 4.5:1) |
| `--gain` / `--loss` / `--warn` | #3ddc97 / #ff6b6b / #f2b24a | #0f7b4f / #c2281d / #9a5b00 | tone, never decoration |
| `--gain-soft` / `--loss-soft` | gain / loss 14% over `--surface` | 10% over `--surface` | chip fills |
| `--glow` | radial gray, #2a2a2e to #18181b to `--bg` | radial gray, #ececef to #f4f4f5 to `--surface` | the Hero background |
| `--chart-1`…`--chart-6` | #3987e5 #d95926 #199e70 #c98500 #d55181 #008300 | #2a78d6 #eb6834 #1baf7a #eda100 #e87ba4 #008300 | chart series, in this order, never cycled (dataviz-validated) |
| `--heat-neg-3`…`--heat-0`…`--heat-pos-3` | `--loss` / `--gain` mixed 22/36/50% into `--surface`; 0 = `--surface-2` | same, at 22/48/65% | heatmap cells by % change (`heatColor`) |

Section colours (owner, 2026-10-30): `--accent`, `--accent-ink`, `--accent-soft` and `--glow` follow the main
section, set as `data-section` on `<html>` by `Layout` from `layout/tabs.js::sectionOf` (no active tab = home):

| section | dark accent / ink | light accent / ink |
|---|---|---|
| home | #60a5fa / #04122b | #1d4ed8 / #ffffff |
| money | #fbbf24 / #1f1300 | #b45309 / #ffffff |
| ideas | #a78bfa / #160b33 | #6d28d9 / #ffffff |
| ai | #22d3ee / #032027 | #0e7490 / #ffffff |
| market | #f472b6 / #2b0717 | #be185d / #ffffff |

`--accent-soft` is the accent mixed into `--surface` (18% dark, 14% light); `--glow` a radial of the accent into
`--bg` (dark) / `--surface` (light). The green `--accent` above is the base, for pages outside `Layout` (Login).
`theme.test.js` checks ink on each accent and each accent on bg/surface at >= 4.5:1.

Rules: neutrals (bg, surfaces, border, text) are true grays with no green cast (owner, 2026-10-30; `theme.test.js` checks it);
green is for `--accent`, gain and badges. `--accent` never colours a number; numbers use `--gain`/`--loss`/`--text`, and every gain or loss carries
a sign or ▲/▼. No raw hex in components: tokens only. A contrast test (`src/theme.test.js`) covers both themes.
The old names (`--paper`, `--ink`, `--rule`, `--stamp`) are aliases until the last component using them is rebuilt.

## Type

Geist (Google Fonts, 400/500/600/700/800), fallback `ui-sans-serif, system-ui, sans-serif`. Scale tokens
`--fs-12/13/15/17/22/28/44`; body 15 px, nothing functional below 12 px. Hero number (`.hero-num`): 44 px,
800, letter-spacing -0.04em, line-height 1, tabular figures. Section labels: 13 px semibold `--text-muted`,
sentence case. Page titles (`PageHeader`): 22 px bold, -0.02em.

## Shape

Radius: 12 controls, 20 cards, 28 hero, 999 pills. 1 px `--border`; no box shadows in dark. 4 px spacing grid,
44 px touch targets.

## Primitives and signature components (`frontend/src/components/ui/`)

`Tile`, `Card`, `Stat`, `Tabs` (+ `useTabParam`, URL `?tab=`; segmented pill, active `--surface` on `--surface-2`),
`ListRow` (`dense` = 36 px trader-list row), `Badge` (pill: proven / unproven / paper / live / alert / neutral),
`Button` (primary = `--accent` fill + `--accent-ink`, secondary, danger; 44 px, radius 12), `PageHeader`, `Empty`,
`Skeleton` (shimmer in `--surface-2`), `ErrorLine`; `format.js` for money and percent text; `chartTheme.js`
(`AXIS`, `GRID`, `SERIES`, `TOOLTIP_STYLE`, `heatColor`) for every recharts chart.

- `Hero({ label, value, format, change, children, to })`: radius 28, `var(--glow)`, `--border`; `value` in the hero
  number (money carries `private`); `change` slot takes a `DeltaChip`; `children` is the footer row; `to` makes it
  a link. At most one per page (Home today).
- `DeltaChip({ value, pct, suffix })`: pill on `--gain-soft` / `--loss-soft`, ▲ / ▼ prefix, `value` in rupees,
  `pct` in percent units; 0 renders neutral (`--surface-2`, no arrow); carries `private`.
- `GradeTile({ grade })`: 40 px, radius 12; A = `--accent` + `--accent-ink`, B = `--surface-2` + `--text`,
  C = transparent + `--border` + `--text-muted`; `aria-label="Grade A"`.

Chrome: `layout/Header` (logo "NeoTrade" 18 px 700, `MarketDot`), `BottomTabs` and `SideRail` (active = `--accent`,
inactive = `--text-muted`, `--surface` bar with `--border` line).

## Motion (CSS, no library)

`.tap` press (scale .98, 120 ms) on rows, buttons and linked cards; Hero count-up 0 to value over 600 ms on first
mount only; `.fade-in` 150 ms on tab panels. All off under `prefers-reduced-motion: reduce`.

## Rules

- Every data section: Skeleton while loading, a one-line error with Retry, an Empty that offers the action
  that fills it. One failing section never blanks a page.
- Money the user owns carries the `private` class so the header's hide-amounts toggle blurs it.
- Navigation: five tabs (Home, Money, Ideas, AI, Market) as a bottom bar on phones and a left rail on desktop;
  the header holds search, market dot, privacy, theme and profile/settings; on phones the theme button is hidden and
  theme is set in Settings.
- Colour is never the only carrier of meaning: gains and losses carry a sign; heat cells print their signed %;
  charts with 2+ series show a legend (light-mode chart slots 3-5 sit below 3:1 on white).
