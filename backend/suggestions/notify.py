"""Text builders for engine proposals and exits, plus `is_admin`. Sending is
`backend/alerts.py`'s job."""


async def is_admin(db, user_id: str) -> bool:
    user = await db["users"].find_one({"id": user_id}, {"role": 1})
    return bool(user) and user.get("role") == "admin"


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
    return "\n".join(lines)


def exit_line(c: dict) -> str:
    return f"{c['reason']} at {_money(c['price'])} · bought {_money(c['entry_price'])} · gross {_money(c['gross_pnl'])}"
