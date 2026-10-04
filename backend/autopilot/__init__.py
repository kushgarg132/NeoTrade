"""The fenced autopilot: AI and engine orders placed on the AI account
(role "ai", backend/brokers/roles.py) without a user tap -- a user-approved
exception to "model output never places an order", allowed only through
fence.check. See docs/superpowers/specs/2026-10-04-dual-broker-accounts-design.md."""
