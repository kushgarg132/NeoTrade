---
name: NeoTrade
description: A broker's contract note, kept live — trading cockpit for Indian equities and F&O
colors:
  paper:
    light: "#f4f4f1"
    dark: "#14150f"
  paper-sunk:
    light: "#e8e8e3"
    dark: "#1c1d16"
  ink:
    light: "#17181b"
    dark: "#eae7d8"
  ink-soft:
    light: "#55575e"
    dark: "#a09d8f"
  ink-faint:
    light: "#8b8d95"
    dark: "#6c6a5f"
  rule:
    light: "#c9c9c2"
    dark: "#33342a"
  rule-strong:
    light: "#17181b"
    dark: "#6f6f60"
  stamp:
    light: "#3a32a0"
    dark: "#8b81ff"
  stamp-soft:
    light: "#ecebf8"
    dark: "#23224a"
  gain:
    light: "#12694a"
    dark: "#5fbb8c"
  loss:
    light: "#a52f1c"
    dark: "#e0705a"
  gain-wash:
    light: "#e2eee8"
    dark: "#1a2a22"
  loss-wash:
    light: "#f6e5e1"
    dark: "#2e1c18"
typography:
  display:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 700
    fontSize: "clamp(2rem, 11vw, 3.25rem)"
    lineHeight: 1
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 400
    fontSize: "0.875rem"
    lineHeight: 1.5
  label:
    fontFamily: "Archivo Narrow, sans-serif"
    fontWeight: 600
    fontSize: "0.6875rem"
    letterSpacing: "0.11em"
    textTransform: "uppercase"
  mono:
    fontFamily: "Courier Prime, ui-monospace, monospace"
    fontSize: "0.6875rem"
    letterSpacing: "0.04em"
    textTransform: "uppercase"
rounded:
  all: "0px"
spacing:
  sheet-padding: "16px"
  field-gap: "12px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.all}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.stamp}"
  button-approve:
    backgroundColor: "{colors.gain}"
    textColor: "#ffffff"
    rounded: "{rounded.all}"
    padding: "0 16px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.all}"
    padding: "0 16px"
    height: "40px"
  input-field:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.all}"
    padding: "8px 0"
---

# Design System: NeoTrade

## Overview

**Creative North Star: "The Contract Note"**

Every NSE trader already reads a contract note — the broker's ruled statement issued after a
day's execution: boxed fields, hairline rules, a double rule under the net, typewriter document
furniture, one rubber stamp for authority. This product is that document, kept alive: the same
ruled sheets, but the figures update under a live socket instead of arriving once at close.

The direction was one of seven grounded candidates dealt by the project's direction roll (seed
key `69b9154f`) and chosen deliberately over the roll's own assignment ("Calibrated Instrument" —
a machined gauge-panel world) and over "Terminal Bands" (airport wayfinding, declined for
carrying no gain/loss colour channel). It is also, knowingly, the closest of the seven to the
category default for "serious Indian fintech" — a trade the operator made with eyes open, for
maximum recognition on a document type every user of this product already trusts.

Light is the default rendition, not dark — the product's own use scene (a phone, in Indian
daylight, checked in a glance during the 09:15–15:30 IST session) ruled it out. Dark mode is
built as the *carbon copy*: the same document, ink gone grey-green, stamp gone bright violet —
never a simple inversion of the light palette's roles.

**Key Characteristics:**
- Square corners everywhere; the only curve in the system is the stamp's own rotation.
- One accent colour (the stamp violet) carries all authority — pending state, the AI conviction
  cap, a rubber-stamped decision — and appears nowhere else.
- Every numeral is tabular and signed; a net is never shown without its sign.
- Live/stale/offline is a stated fact in the masthead, never an implied one.

## Colors

Printed-document ink on office-bond paper, not screen neon. Gain and loss use the muted green/red
of an actual ledger stamp, not saturated success/error UI colours.

### Primary
- **Stamp Violet** (`#3a32a0`, dark `#8b81ff`): the one authority colour. Used only for the AI
  conviction-cap mark, the live-feed dot, pending-decision affordances, and the rubber stamp
  itself. Never used for a button that isn't a live-data or decision action.

### Neutral
- **Paper** (`#f4f4f1`, dark `#14150f`): the sheet ground.
- **Paper Sunk** (`#e8e8e3`, dark `#1c1d16`): section header bands, the sidebar, hover states —
  one step recessed from the sheet.
- **Ink** (`#17181b`, dark `#eae7d8`): primary text and the border-strong rule colour.
- **Ink Soft** (`#55575e`, dark `#a09d8f`): secondary text, field hints.
- **Ink Faint** (`#8b8d95`, dark `#6c6a5f`): placeholders, timestamps, disabled affordances.
- **Rule** (`#c9c9c2`, dark `#33342a`): hairline dividers between rows.
- **Rule Strong** (`#17181b`, dark `#6f6f60`): sheet borders, the double net rule, input underlines.

### Semantic (Gain / Loss)
- **Gain** (`#12694a`, dark `#5fbb8c`) / **Gain Wash** (`#e2eee8`, dark `#1a2a22`): positive P&L,
  approved-stamp tone, target levels.
- **Loss** (`#a52f1c`, dark `#e0705a`) / **Loss Wash** (`#f6e5e1`, dark `#2e1c18`): negative P&L,
  rejected-stamp tone, stop levels.

### Named Rules
**The One Ink Rule.** Every colour on the page must mean exactly one of: neutral text, a rule
line, gain, loss, or stamp authority. A fifth colour introduced for decoration is a violation —
if something needs emphasis and none of the four apply, use weight or size instead.

## Typography

**Display / Body Font:** Archivo (with ui-sans-serif, system-ui fallback)
**Label Font:** Archivo Narrow (condensed, tracked caps — the printed form-field voice)
**Document Font:** Courier Prime (machine-stamped furniture only: note numbers, timestamps, seals)

**Character:** A grotesk built for reading numbers at speed, paired with a condensed narrow face
for the "official form" field-label register, and a genuine typewriter face reserved strictly for
document furniture — never for prose, so it stays a signal rather than a costume.

### Hierarchy
- **Figure Large** (700, `clamp(2rem, 11vw, 3.25rem)`, tabular-nums, tight tracking `-0.02em`):
  a statement's net figure — today's net, realised-all-time. At most one per sheet.
- **Figure Medium** (600, ~1rem, tabular-nums, `-0.01em`): every other money or count value in a
  table cell or field.
- **Body** (400, 0.875rem): prose — theses, descriptions, empty-state copy.
- **Field Label** (Archivo Narrow, 600, 0.6875rem, `0.11em` tracking, uppercase): every field name,
  sheet title, tab label, button label.
- **Doc Meta** (Courier Prime, 0.6875rem, `0.04em` tracking, uppercase): timestamps, note numbers,
  "LIVE / MARKET CLOSED" status — the machine-stamped register.

### Named Rules
**The Tabular Numerals Rule.** `font-variant-numeric: tabular-nums` is set globally on `body`.
No money or quantity figure may use proportional numerals — columns must always align like a
real ledger.

**The Signed Net Rule.** A profit/loss figure is never rendered without an explicit `+`/`−` sign,
even when the value could be inferred from colour alone (`formatSigned`/`formatSignedPercent`).

## Layout

Sheets stack in a single column at a `max-w-6xl` centred rail; nothing sits beside anything else
above `sm` except the two-up P&L summary and 2-3 column figure grids inside a sheet body. Phone is
the primary target (per PRODUCT.md's own use-scene finding): a fixed bottom nav (`grid-cols-5`,
safe-area aware) carries the five primary sections and the live pending-decision count; a desktop
sidebar (`w-56`, `hidden lg:flex`) replaces it above `lg`. Tables collapse to stacked "record"
cards under `sm` rather than scrolling horizontally — a statement column you have to swipe to
reach is a column nobody reads. Spacing rhythm is `space-y-4` between sheets, `p-4` sheet body
padding, `py-1.5`–`py-3` row rhythm inside a sheet.

The app installs to a phone's home screen (`public/manifest.webmanifest`, `public/sw.js`). The
icon (`public/icon.svg`, rasterised to `icon-192/512.png` and `apple-touch-icon.png`) is the
stamp on office bond: a stamp-violet double-bordered box around an "N", over a double net rule,
drawn from shapes only so every raster matches. Installed, the masthead pads for
`safe-area-inset-top`, and form fields render at 16px under `lg` so iOS never zooms into them.

## Elevation & Depth

Flat by default — sheets are drawn with a 1px border, not a shadow, matching a printed page lying
on a desk. `--sheet-shadow` is a soft, low-opacity ambient shadow (`0 1px 2px … , 0 8px 24px -12px …`)
used only to lift a sheet fractionally off the page ground; it is never used to imply interactivity
or hover response. Depth increases with document hierarchy (a sheet is slightly lifted; a header
band inside it is flat, one step darker) rather than with shadow blur.

### Named Rules
**The Ruled-Not-Shadowed Rule.** Separation between regions is a border or rule line first;
reach for `--sheet-shadow` only at the outermost sheet boundary, never between rows or fields
within one.

## Shapes

Every corner in the system is square (`--radius-*: 0px`). The one deliberate exception is the
rubber stamp (`.stamp-land`), which lands rotated `-4deg` — the single non-orthogonal element on
the page, and precisely because it is singular, it reads as a stamp rather than as a UI affordance.

## Components

### Buttons (`common/Button.jsx`)
- **Shape:** square corners, 1px border always visible (even on the filled `primary` variant).
- **Primary:** ink background / paper text, hover shifts to stamp violet — the only place stamp
  violet fills a solid surface.
- **Approve:** dedicated `gain`-filled variant, used only on the decisions inbox's Approve action.
- **Secondary / Outline / Ghost:** paper background, ink-soft text, border-strong on hover.
- **Label voice:** Archivo Narrow, uppercase, `0.11em` tracking on every variant — a button reads
  as a printed instruction, not a rounded chip.

### Cards / Sheets (`components/doc/Doc.jsx` `Sheet`, `common/Card.jsx`)
- **Corner Style:** square, always.
- **Background:** `paper`; header band `paper-sunk`.
- **Shadow Strategy:** `--sheet-shadow` at the outer boundary only (see Elevation).
- **Border:** 1px `rule-strong` around the whole sheet; 1px `rule` between header and body.
- **Internal Padding:** `p-4` body, `px-4 py-2.5` header band.

### Inputs / Fields (`common/Input.jsx`, search fields)
- **Style:** no box — a single 2px underline (`border-b-2 border-rule-strong`), transparent fill.
- **Focus:** underline colour shifts to stamp violet; no glow, no ring.
- **Placeholder:** `ink-faint`.

### Statement tables (`doc/Doc.jsx` `Statement`/`Row`/`Cell`)
- Column headers are Field Label style with a `border-b-2 rule-strong` rule beneath them; rows
  separated by 1px `rule`, no zebra striping. A closing total uses `NetLine` — a 3px double rule
  (`border-top: 3px double`) above the figure, the literal "net" line of a real contract note.
- Below `sm` every `Statement` reflows into stacked records by itself (`.statement` in
  `index.css`): the first cell heads the record full-width, every other cell prints under its
  column's label (passed down by `Row` as `data-label`), and a label-less column holds row
  actions at the record's far edge. So put the identifying column (the scrip) first.
- Money never breaks between its sign and its figure (`Money` is `whitespace-nowrap`); a
  `NetLine` drops its figure under the label rather than overflowing.

### The Stamp (`doc/Doc.jsx` `Stamp`, `.stamp-land` keyframes)
A boxed, rotated (-4deg), coloured-border mark used exclusively to represent a *decided* state
(Approved / Declined / Executed) on a suggestion record. It is the system's one signature
component and its one authored motion: 420ms scale-and-settle on arrival, everything else in the
system is static or a plain colour/opacity transition.

### Navigation
- **Desktop sidebar:** `w-56`, `paper-sunk` ground, active item marked by a 2px stamp-violet left
  border plus a `paper` background — never a filled pill.
- **Mobile bottom nav:** 5 items, active item marked by a 2px stamp-violet top border; pending
  count renders as a small solid-stamp badge on the Decisions icon.
- Both share one label voice: Field Label style, never body text.

## Do's and Don'ts

### Do:
- **Do** use tabular numerals and an explicit sign on every money and percentage figure.
- **Do** reserve stamp violet for authority/live/pending states only — check every new use against
  the One Ink Rule before adding a colour.
- **Do** close every summed table with a `NetLine` double rule rather than a plain bold total row.
- **Do** collapse tables to stacked records below `sm`; never let a statement table force
  horizontal scroll on a phone.
- **Do** state live/stale/offline explicitly in the UI (the masthead `FeedStatus` pattern) rather
  than letting a page look identical whether or not its data is current.

### Don't:
- **Don't** round a corner. If a component needs to look "softer", that is not this system's
  vocabulary — use spacing or weight instead.
- **Don't** add a drop shadow between two elements inside the same sheet; use a rule line.
- **Don't** show an unsigned or unlabelled number where money or percentage is meant — `—` for
  unknown, always a `+`/`−` otherwise.
- **Don't** use the stamp violet as a generic "brand colour" accent on non-authority UI (e.g. a
  decorative header rule, an unrelated icon tint).
- **Don't** animate anything beyond the stamp-land and restrike keyframes without a stated reason;
  this world has exactly one authored motion moment.
