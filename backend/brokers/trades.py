"""Shared parsing for broker trade books: every broker reports execution
times as IST wall-clock, in its own string format (or, for pykiteconnect, a
naive datetime it already parsed). This is the one place that turns any of
them into an aware UTC datetime."""

from datetime import date, datetime, timezone

from backend.engine.session import IST

# Upstox's docs only say "user readable"; both shapes seen in its examples
# are accepted rather than guessing one.
_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S")


def parse_ist(value, on_day: date | None = None) -> datetime:
    """`value` is a datetime (naive = IST), a full timestamp string, or --
    Angel One's trade book -- a bare "HH:MM:SS", which needs `on_day`."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if on_day is not None and len(text) == 8 and text.count(":") == 2:
            parsed = datetime.combine(on_day, datetime.strptime(text, "%H:%M:%S").time())
        else:
            for fmt in _FORMATS:
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Unrecognized broker timestamp: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(timezone.utc)


def today_ist() -> date:
    return datetime.now(timezone.utc).astimezone(IST).date()
