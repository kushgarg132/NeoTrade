# Detail pages redesign: one Hero per page

Date: 2026-10-27. Status: approved in chat. Sub-project 6 of the whole-app UX overhaul
(identity: `2026-10-27-visual-identity-design.md`; primitives as extended in
`2026-10-27-market-stock-redesign-design.md`: Hero/DeltaChip `privateValue`, DeltaChip `format`).
Frontend only, no backend change.

## Intent

- Owner: each detail page's main figure on the Hero; other cards stay; leftovers (incl. `components/doc/Doc.jsx`) go.
- Owner rule: every feature, control, link and piece of data stays; simplest result.
- Hero shows only when its figure exists (closed trade, strategy with trades, week with a curve);
  otherwise the page looks as today.

`signedInr = (v) => inr(v, { sign: true })`, `signedPct = (v) => pct(v, { sign: true })` (local consts where used).

## 1. Trade pages

- `pages/RoundTrip.jsx` (`Body`): when `trip.pnl !== null`, `<Hero label="P&L" value={trip.pnl} format={signedInr} />`
  above the existing Card. In the Card, the P&L `Stat` renders only when open (shows "Open" as today);
  Held, Average entry/exit (`private` wrappers), title, View stock, NewsChips unchanged.
- `pages/AiTrade.jsx`: when `!s.open`, `<Hero label="Net" value={s.net} format={signedInr} />` above the
  Result Card; the Card's Net `Stat` is removed; Entry, Exit, Quantity, Held, Gross, Costs, Exit reason,
  Open badge, "Open {symbol}" link unchanged.
- Both Heroes keep the default `privateValue` (blurred under hide-amounts).

## 2. Summary pages

- `pages/AiStrategy.jsx`: when `row` exists, the Paper record Card is replaced by
  `<Hero label="Net · paper" value={row.net} format={signedInr}>` with children
  `grid grid-cols-3 gap-3 mt-3` of the Open, vs NIFTY and Win rate `Stat`s (same props). Loading,
  error and "No trades yet" stay in the Card titled "Paper record".
- `pages/WeeklyReport.jsx`: when `r.you.ret != null`, the "Your account against NIFTY" Card becomes
  `<Hero label="Your account this week" value={r.you.ret} format={signedPct} privateValue={false}>` with
  children `grid grid-cols-2 gap-3 mt-3` of the NIFTY and Excess `Stat`s. The "No curve" Empty (with
  Connect link) stays in that Card. `act` link class: `text-[var(--surface)]` -> `text-[var(--accent-ink)]`.
- `pages/IdeaDetail.jsx`:
  - Badge row: grade `Badge` -> `<GradeTile grade={idea.grade} />` (same `GRADES[idea.grade]` guard).
  - Expected return Card: the `text-[24px]` span -> `<DeltaChip pct={idea.expectedMedian * 100} privateValue={false} />`;
    `when`, rupees, spread lines unchanged.
  - `Fold`: `rounded-[16px]` -> `rounded-[20px]`.

## 3. Leftovers

- `pages/Strategies.jsx`: `SUMMARY_CLS` and the list `ul`: `rounded-[16px]` -> `rounded-[20px]`.
- `components/doc/Doc.jsx`: empty box `rounded-[16px] border border-dashed` -> `rounded-[20px] border`;
  chip `--gain-wash`/`--loss-wash` -> `-soft`; segmented toggle drop `shadow-sm`; count badge
  `text-[var(--surface)]` on accent -> `text-[var(--accent-ink)]`. `doc-meta` stays.
- `docs/wiki/frontend.md`: detail page sections; `verified_at`.

## 4. Tests and checks

- Source tests per page: Hero present and gated (`trip.pnl !== null`, `!s.open`, `row`, `r.you.ret != null`);
  open-trade "Open" kept; no Net Stat on AiTrade, no P&L Stat when closed on RoundTrip; WeeklyReport Hero
  and IdeaDetail chip `privateValue={false}`; IdeaDetail imports `GradeTile`, no grade `Badge`, no `text-[24px]`.
- Source test over Strategies.jsx, Doc.jsx, IdeaDetail.jsx, WeeklyReport.jsx: no `rounded-[16px]`,
  `border-dashed`, `-wash)`, `shadow-sm`, accent+surface pair.
- `npm test && npm run lint && npm run build` green.
- Playwright 390x844, both themes, mocked API: RoundTrip open + closed; AiTrade open + closed; AiStrategy
  with trades + empty; WeeklyReport with curve + without; IdeaDetail graded pick; Strategies. `scrollWidth <= 390`.
- Deploy Direct (`[skip ci]`), frontend only.

## Out of scope

Login, Settings, Lab (sub-project 7); backend; `doc-meta` uses.
