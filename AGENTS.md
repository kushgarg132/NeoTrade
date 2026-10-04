# NeoTrade working context

NeoTrade is the personal trading assistant at `/home/ubuntu/projects/NeoTrade`.
Its FastAPI backend is deployed on the host at `https://neotrade.161.118.167.148.nip.io`; the
Vercel frontend is `https://neotrade-trading.vercel.app`. The old `ai-stock` host is retired.

## Current user goal

The user wants to use their Telegram bot as an AI interface for NeoTrade. Treat Telegram as an
additional client of NeoTrade's existing AI and trading workflows, not as a bypass around them.
Before implementation, identify the bot's current code/token ownership and the intended scope:
information and alerts only, AI analysis, or confirmable trading actions.

## Safety requirements

- Never expose, commit, print, or place bot tokens, broker credentials, or API secrets in source.
- All user data must remain scoped to the authenticated NeoTrade user.
- A message or model output may propose an action but must not place an order directly.
  Exception (user-approved 2026-10-04): `backend/autopilot/` may place orders without a user tap
  on the broker whose role is `ai` (`backend/brokers/roles.py`) only, after `autopilot/fence.check`
  passes; the kill switch still applies, and nothing may route an AI order to the user's own
  (`mine`) account. See `docs/superpowers/specs/2026-10-04-dual-broker-accounts-design.md`.
- Re-check all risk controls, broker state, and current market conditions at confirmation time.
- Live orders require an explicit second confirmation; do not weaken this flow for Telegram.

## Relevant design already in the repository

`docs/superpowers/specs/2026-10-04-chat-assistant-design.md` and its companion implementation
plan describe an approved NeoTrade AI assistant: per-user data snapshots, bound read tools, and
confirmable action cards. Reuse this architecture for any Telegram integration rather than
creating a separate unrestricted trading path.

## Working-tree note

Before making changes, preserve the user’s existing edits to `frontend/package.json` and
`frontend/package-lock.json`. Do not overwrite or discard them.

## Host and deployment

The host-level instructions are in `/home/ubuntu/AGY.md`. Read them before deployment work.
Do not push changes unless the user asks for it; before the first push in a session, follow its
required deploy-mode question.
