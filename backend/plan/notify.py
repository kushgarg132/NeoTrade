"""Game plans on Telegram: the pre-open plan and every revision, through
the user's own alert channel (backend/guardrails), with the autopilot's
stop button. Fallback plans are not sent: they change nothing."""

import logging

logger = logging.getLogger(__name__)
MAX_SYMBOLS = 8
LABELS = {"regime_flip": "Regime change", "event_passed": "Event passed"}


def plan_text(doc: dict) -> str:
    trigger = doc.get("trigger") or ""
    if trigger == "pre_open":
        lines = ["📋 Today's plan"]
    else:
        label = "News" if trigger.startswith("news:") else LABELS.get(trigger, trigger)
        lines = [f"🔁 Plan updated ({label})"]
    lines += [f"• {line}" for line in doc.get("rationale") or []]
    if doc.get("skip_day"):
        lines.append("Sitting today out: no new intraday entries.")
    lines.append(f"Risk {float(doc.get('risk_multiplier', 1.0)):.2f}× · up to {doc.get('max_positions')} positions")
    symbols = [a["symbol"] for a in doc.get("allow") or []]
    if symbols:
        more = f" +{len(symbols) - MAX_SYMBOLS} more" if len(symbols) > MAX_SYMBOLS else ""
        lines.append(f"Trading: {', '.join(symbols[:MAX_SYMBOLS])}{more}")
    if doc.get("add_symbols"):
        lines.append(f"Added: {', '.join(doc['add_symbols'])}")
    lines += [f"Exit {e['symbol']}: {e.get('reason', '')}" for e in doc.get("exits") or []]
    return "\n".join(lines)


async def notify_plan(db, user_id: str, doc: dict) -> bool:
    from backend.autopilot.service import STOP_BUTTON
    from backend.guardrails import telegram
    from backend.guardrails.store import GuardrailStore

    try:
        channel = await GuardrailStore(db).telegram_channel(user_id)
        if channel is None:
            return False
        token, chat_id = channel
        return await telegram.send_buttons(chat_id, plan_text(doc), STOP_BUTTON, token)
    except Exception as exc:
        logger.warning("could not send the game plan to %s: %s", user_id, exc)
        return False
