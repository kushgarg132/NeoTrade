"""The WebSocket authenticates with ?token=<JWT>; uvicorn's access log wrote
the full path, so session tokens sat in the container logs."""

import logging

from backend.log_redaction import RedactTokens


def _record(path):
    # uvicorn.access formats: '%s - "%s %s HTTP/%s" %d' % (client, method, path, version, status)
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                             '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "GET", path, "1.1", 101), None)


def test_token_query_is_redacted():
    record = _record("/api/v1/ws?token=eyJhbGciOi.secret.sig")
    assert RedactTokens().filter(record) is True
    assert "eyJ" not in record.getMessage() and "token=REDACTED" in record.getMessage()


def test_other_paths_are_untouched():
    record = _record("/api/v1/scanner?x=1")
    RedactTokens().filter(record)
    assert "/api/v1/scanner?x=1" in record.getMessage()
