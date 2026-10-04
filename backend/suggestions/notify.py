"""Telegram messages about the long-term engine: new proposals, the morning
digest, and automatic exits. Same bot and chat as the guardrail alerts
(backend/guardrails/telegram.py:alert); best effort, and a no-op for a user
who never linked Telegram."""

from backend.guardrails import telegram


async def notify(db, user_id: str, text: str) -> bool:
    return await telegram.alert(db, user_id, text)


def _money(value) -> str:
    return "—" if value is None else f"₹{value:,.2f}"


def proposals_text(suggestions: list[dict], heading: str) -> str:
    lines = [heading]
    for s in suggestions[:15]:
        lines.append(
            f"• {s.get('side', '')} {s.get('symbol', '?')} x{s.get('quantity') or 0:g} @ ~{_money(s.get('entry_ref'))}"
            f" · stop {_money(s.get('stop'))} · target {_money(s.get('target'))}"
        )
    if len(suggestions) > 15:
        lines.append(f"…and {len(suggestions) - 15} more")
    lines.append("Decide under Paper → Decisions.")
    return "\n".join(lines)


def exits_text(closed: list[dict]) -> str:
    lines = ["Long-term paper position(s) closed:"]
    for c in closed:
        lines.append(
            f"• {c['symbol']} x{c['quantity']:g} at {_money(c['price'])} ({c['reason']}),"
            f" bought {_money(c['entry_price'])}, gross {_money(c['gross_pnl'])}"
        )
    return "\n".join(lines)
