# NeoTrade design system

A calm, phone-first money app: one task per screen, big numbers, plain words. Replaces the earlier
"contract note" look (paper, ink, stamp, square corners). The tokens are real, in `frontend/src/index.css`.

## Tokens (light / dark)

| token | light | dark | use |
|---|---|---|---|
| `--bg` | #f6f7f9 | #0e1117 | page |
| `--surface` | #ffffff | #161b24 | cards, header, tabs bar |
| `--surface-2` | #eef0f4 | #1f2531 | segmented control, pressed rows, skeleton |
| `--border` | #dde1e8 | #2b3242 | hairlines |
| `--text` | #14171f | #e8ebf1 | primary text |
| `--text-muted` | #566070 | #9ba5b5 | secondary text (>= 4.5:1 on bg and surface) |
| `--accent` | #4338ca | #8f97ff | links, active tab, primary button |
| `--gain` / `--loss` / `--warn` | #0d7a4e / #b42318 / #9a5b00 | #4cc38a / #f07167 / #e2a63b | tone, never decoration |

Radius 12 (controls) and 16 (cards). Spacing on a 4 px grid. Body 15 px, nothing functional below 12 px,
touch targets 44 px. Numbers use tabular figures. No raw hex in components: tokens only. The old
names (`--paper`, `--ink`, `--rule`, `--stamp`) are aliases until the last component using them is rebuilt.

## Primitives (`frontend/src/components/ui/`)

`Tile`, `Card`, `Stat`, `Tabs` (+ `useTabParam`, URL `?tab=`), `ListRow`, `Badge`
(proven / unproven / paper / live / alert / neutral), `Button` (primary / secondary / danger),
`PageHeader`, `Empty`, `Skeleton`, `ErrorLine`; `format.js` for money and percent text.

## Rules

- Every data section: Skeleton while loading, a one-line error with Retry, an Empty that offers the action
  that fills it. One failing section never blanks a page.
- Money the user owns carries the `private` class so the header's hide-amounts toggle blurs it.
- Navigation: five tabs (Home, Money, Ideas, AI, Market) as a bottom bar on phones and a left rail on desktop;
  the header holds search, market dot, privacy, theme and profile/settings.
- Colour is never the only carrier of meaning: gains and losses carry a sign.
