# Autopilot news trigger and regime fence (extends the 2026-10-04 exception)

User-approved 2026-10-05. Extends the AI-account autopilot exception in
`docs/superpowers/specs/2026-10-04-dual-broker-accounts-design.md`; nothing here
touches the user's own (`mine`) account, the kill switch, or the backtest gate
for anything outside `backend/autopilot/`.

## What it allows

- **News entries.** A PENDING `source="news"` proposal (`backend/datalayer/reactor.py`
  `scan`, same strategies and `composite.py` scoring as any scan) may be submitted to
  `autopilot.service.submit` right away, `source="news"`, instead of waiting for the
  next morning pass. Only when the new pref `autopilot_news` is on (default **off**)
  and the autopilot is on; paper unless `autopilot_live`; through `fence.check`.
- **News exits, shadow only.** A material negative item (impact >= 8, direction <= -0.5,
  on the symbol or its sector) on an autopilot long is recorded in `autopilot_shadow`
  as the SELL it would place. No order is sent. Enabling real news exits is a separate,
  reviewed change after >= 2 weeks of shadow log.

## What it adds to the fence (only tightens)

`fence.check`, for entries (BUY) only; exits are never blocked:

| Condition | Effect |
|---|---|
| `market:regime` label `risk_off` (score <= -0.5) | per-trade cap halved for every entry; news entries refused |
| a high-impact calendar event within 30 min (`market:regime.event_soon`) | every entry refused |
| `source="news"` and `autopilot_news` off | refused |
| `source="news"` and 3 news entries already today | refused |

A missing or expired regime (ingest down) adds no rule: the fence is exactly what it
was before this change, never looser.
