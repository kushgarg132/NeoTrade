"""Keeps session tokens out of the access log. The live socket authenticates
with ?token=<JWT> in its URL (backend/ws/routes.py), and uvicorn printed the
full path: HTTP lines on uvicorn.access, WebSocket handshakes on uvicorn.error."""

import logging
import re

_TOKEN = re.compile(r"(token=)[^&\s\"]+")


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(_TOKEN.sub(r"\1REDACTED", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = _TOKEN.sub(r"\1REDACTED", record.msg)
        return True


def install() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactTokens())
