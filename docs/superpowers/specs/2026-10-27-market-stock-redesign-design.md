# Market + Stock redesign: public prices on the Hero

Date: 2026-10-27. Status: approved in chat. Sub-project 5 of the whole-app UX overhaul
(identity: `2026-10-27-visual-identity-design.md`). Frontend only, no backend change.

## Intent

- Owner: Stock price, index level and a NIFTY hero on Market Today use the identity's Hero; leftovers go.
- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Hide-amounts must never blur public prices (index levels, stock quotes), same rule as
  `ListRow privateValue={false}`; the user's own position figures stay blurred.

## 1. Primitives (`frontend/src/components/ui/`)

- `format.js`: new `points(n, { sign = false } = {})`: en-IN grouping, up to 2 decimals, `'—'` for
  non-finite, `+` for positive when `sign`. Example: `points(24812.5, { sign: true })` = `"+24,812.5"`.
- `Hero`: new prop `privateValue = true`; the value div carries `private` only when true.
- `DeltaChip`: new props `format = inr`, `privateValue = true`.
  - Direction (arrow, colour, fill) = sign of `value`, or of `pct` when `value` is not a number.
  - The amount part renders `format(value, { sign: true })` only when `value` is a number; percent part
    as today. `private` only when `privateValue`.
- Defaults keep Home, Money, AI unchanged.

## 2. Stock (`frontend/src/pages/Stock.jsx`)

- When price loaded: `<Hero label={company?.name || symbol} value={price}
  format={currency === 'INR' ? inr : points} privateValue={false}
  change={dayPct != null && <DeltaChip value={currency === 'INR' ? dayAbs : null} pct={dayPct * 100}
  suffix={marketPhase() === 'open' ? 'today' : 'last session'} privateValue={false} />}>`
  with children: the Watch toggle (same button, same `aria-pressed`) and `<AsOf at={live?.at} />`.
- Loading / error of the price stay in a `Card` as now.
- The position block (`pos` stats, stop line, "Set one in Details"), the sold line and the mine
  `ErrorLine` move into a `Card` below the Hero, unchanged; that Card renders only when one of them shows.
- `PageHeader` verdict badge, `AiRead`, tabs unchanged.

## 3. Market Today and Index

- `components/market/Today.jsx`: `useSection(loadIndices)` lifts from `Indices` into `Today`; `Indices`
  takes `{ data, error, retry }` props. Above `Story`, when `data` has `^NSEI`:
  `<Hero to={indexPath('^NSEI')} label="NIFTY 50" value={n.value} format={points} privateValue={false}
  change={<DeltaChip value={n.change} pct={n.percent} format={points} privateValue={false} />} />`.
  Hidden while loading or on error (Indices card shows those states).
- `TILES` drops `'^NSEI'` (shown by the Hero); BANK NIFTY and SENSEX tiles stay; the "more" list unchanged.
- `IndexTile`: `rounded-[16px]` -> `rounded-[20px]`, `tap`.
- `pages/IndexPage.jsx`: when ok, `<Hero label={data.name} value={data.value} format={points} privateValue={false}
  change={<DeltaChip value={data.change} pct={data.percent} format={points} privateValue={false} />} />`, then the
  Card with 52-week range, 50-day, 200-day `Stat`s and `CloseLine` (Level `Stat` removed: the Hero shows it).
- `pages/SectorPage.jsx`: unchanged layout.

## 4. Leftovers

- `components/market/Sectors.jsx` segmented toggle: drop `shadow-sm`.
- `components/market/News.jsx` filter chip on-state and `components/stock/TradingChart.jsx` range + news
  buttons: `text-[var(--surface)]` on `bg-[var(--accent)]` -> `text-[var(--accent-ink)]`.
- `components/trading/OrderTicket.jsx`: `--gain-wash` / `--loss-wash` -> `-soft`; selected
  `bg-[var(--text)] text-[var(--surface)]` stays (not an accent fill).
- `components/trading/TradingControlBar.jsx` alert: `--loss-wash` -> `--loss-soft`.
- `doc-meta` uses stay. `docs/wiki/frontend.md`: Market, Stock, Index sections; `verified_at`.

## 5. Tests and checks

- `format.test.js` (or the existing format test): `points` cases (sign, decimals, null).
- `components/ui/signature.test.js` (extend): Hero `privateValue` gate; DeltaChip `format` prop used for
  the amount, direction from `pct` when `value` null, amount omitted when `value` null, `privateValue` gate.
- Source tests: Stock, IndexPage, Today Heroes all pass `privateValue={false}` (Hero and DeltaChip);
  Stock position Stats/stop line keep `private`; `TILES` has no `^NSEI`; no `rounded-[16px]`, `shadow-sm`,
  `-wash)`, accent+surface pairs in the touched market/stock/trading files.
- `npm test && npm run lint && npm run build` green.
- Playwright 390x844, both themes, mocked API: `/market` each tab; `/stock/RELIANCE` with and without a
  position; a non-INR stock; `/index/%5ENSEI`; one sector page; one shot with hide-amounts on
  (Stock price readable, position blurred). `scrollWidth <= 390`.
- Deploy Direct (`[skip ci]`), frontend only.

## Out of scope

Detail pages (sub-project 6), Login/Settings/Lab (7), backend, chart restyle beyond tokens, `doc-meta`.
