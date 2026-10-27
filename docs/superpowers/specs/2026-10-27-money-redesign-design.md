# Money redesign: Hero on top, same tabs

Date: 2026-10-27. Status: approved in chat. Sub-project 3 of the whole-app UX overhaul
(identity: `2026-10-27-visual-identity-design.md`; Home: `2026-10-27-home-redesign-design.md`).
Frontend only, no backend change.

## Intent

- Owner: Money's headline becomes the identity's Hero; the four tabs stay; leftover old styling goes.
- Owner rule: every feature, control, link and piece of data stays; simplest result.

## 1. Top of Money (`frontend/src/pages/Money.jsx`)

- When `h` (= `overview.headline`) exists, the headline `Card` is replaced by
  `<Hero label="Your broker account" value={h.value} change={<DeltaChip value={h.day_change} pct={h.day_change_pct} suffix="today" />}>`
  (no `to`: already on Money). Children, in order:
  1. Stale badge (`holdingsStale(h.holdings_as_of)` -> `<Badge kind="unproven">Stale · …</Badge>`), unchanged logic.
  2. `grid grid-cols-2 gap-3 mt-3`: `Stat` "Total P&L" (`h.pnl`, `h.pnl_pct`) and `Stat` "Yearly (XIRR)"
     (`formatXirr(h.xirr)`, `NIFTY ${formatXirr(h.nifty_xirr)}`), unchanged props.
  3. The "Put in … / Broker logged out" line, unchanged (keeps `private` on the rupees).
- The "Today" `Stat` is removed: DeltaChip shows the same rupees and percent.
- Error / loading / Empty branches stay in a `Card` as now; the Empty "Connect your broker" link uses
  `text-[var(--accent-ink)]`.
- Tabs, `TABS`, `useTabParam` and every `?tab=` link unchanged.

## 2. Leftovers

At the source (`frontend/src/index.css`):
- `@utility sheet`: `border-radius: 20px` (was 16).
- `@utility doc-meta`: values unchanged (12 px, `--text-muted`); comment rewritten to "Small muted
  meta text (timestamps, notes)". Its 53 uses stay.

Spot fixes:
- `components/money/JournalTab.jsx` broker prompt link: `rounded-[16px] border border-dashed` ->
  `rounded-[20px] border`.
- `components/money/HoldingsTab.jsx`: dialog sheets `rounded-[16px]` / `rounded-t-[16px]` -> 20;
  `Chip` on-state text `text-[var(--surface)]` -> `text-[var(--accent-ink)]`; connect link (line ~170)
  same; `VERDICT` pills `--loss-wash` -> `--loss-soft`, `--gain-wash` -> `--gain-soft`.
- `components/portfolio/Rebalance.jsx` view toggle (line ~284): on-state `text-[var(--surface)]` ->
  `text-[var(--accent-ink)]`. The rule toggle (`bg-[var(--text)] text-[var(--surface)]`, line ~200) stays:
  it is not an accent fill.
- `docs/wiki/frontend.md`: Money section notes Hero + DeltaChip on top; `verified_at` bumped.

## 3. Tests and checks

- `pages/Money.test.js` (extend): imports `Hero` and `DeltaChip`; `<Hero` with `label="Your broker account"`;
  no `label="Today"` Stat; `Total P&L` and `Yearly (XIRR)` still present; `private` on the "Put in" rupees.
- Source test over `pages/Money.jsx`, `components/money/*.jsx`, `components/portfolio/Rebalance.jsx`:
  no `rounded-[16px]`, no `border-dashed`, no `bg-[var(--accent)] text-[var(--surface)]`, no `-wash)`.
- `theme.test.js` or a new assertion: `sheet` utility radius 20.
- `npm test && npm run lint && npm run build` green.
- Playwright 390x844, both themes, mocked API: `/money` each tab (overview, holdings, tax, journal) and
  the empty account; `scrollWidth <= 390`; screenshots reviewed.
- Deploy Direct (`[skip ci]`), frontend only.

## Out of scope

Other pages (sub-projects 4-7), the 53 `doc-meta` uses, backend, charts.
