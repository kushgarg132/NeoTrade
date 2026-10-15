"""Keeps secrets out of the logs:
- session tokens: the live socket authenticates with ?token=<JWT> in its URL
  (backend/ws/routes.py), and uvicorn printed the full path;
- Telegram bot tokens: every Bot API URL carries /bot<id>:<secret>/, and httpx
  logs that URL on each request and inside every HTTPStatusError message
  (seen in the ingest logs on 15 Oct 2026).
The filter sits on every handler, so records from any logger and their
tracebacks are covered."""

import logging
import re

_PATTERNS = (
    (re.compile(r"(token=)[^&\s\"]+"), r"\1REDACTED"),
    (re.compile(r"(bot\d+:)[\w-]+"), r"\1REDACTED"),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg, record.args = redact(message), None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


def install() -> None:
    """On every handler of the root and uvicorn loggers. Call after logging is configured."""
    for name in (None, "uvicorn", "uvicorn.access", "uvicorn.error"):
        log = logging.getLogger(name)
        log.addFilter(RedactTokens())
        for handler in log.handlers:
            handler.addFilter(RedactTokens())
