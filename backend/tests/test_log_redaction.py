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


def test_websocket_handshake_line_is_redacted(caplog):
    """uvicorn logs '"WebSocket <path>" [accepted]' on uvicorn.error, not
    uvicorn.access."""
    from backend.log_redaction import install

    install()
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logging.getLogger("uvicorn.error").info('%s - "WebSocket %s" [accepted]', "1.2.3.4:5",
                                                "/api/v1/ws?token=eyJhbGciOi.secret.sig")
    assert "eyJ" not in caplog.text and "token=REDACTED" in caplog.text


def test_telegram_bot_tokens_are_redacted_from_messages_and_tracebacks():
    import logging

    record = logging.LogRecord("httpx", logging.INFO, __file__, 1,
                               "HTTP Request: POST %s", ("https://api.telegram.org/bot123456:AAH-x_y/sendMessage",), None)
    RedactTokens().filter(record)
    assert record.getMessage() == "HTTP Request: POST https://api.telegram.org/bot123456:REDACTED/sendMessage"

    try:
        raise RuntimeError("Client error '403' for url 'https://api.telegram.org/bot99:secret-tok/getUpdates'")
    except RuntimeError:
        import sys
        failed = logging.LogRecord("x", logging.ERROR, __file__, 1, "polling failed", None, sys.exc_info())
    RedactTokens().filter(failed)
    assert "secret-tok" not in failed.exc_text and "bot99:REDACTED" in failed.exc_text


def test_non_string_message_and_mapping_args_are_redacted():
    url = "https://api.telegram.org/bot42:sekret/getMe"
    as_msg = logging.LogRecord("x", logging.WARNING, __file__, 1, RuntimeError(f"failed for url '{url}'"), None, None)
    as_map = logging.LogRecord("x", logging.INFO, __file__, 1, "GET %(url)s", ({"url": url},), None)
    for record in (as_msg, as_map):
        RedactTokens().filter(record)
        assert "sekret" not in record.getMessage() and "bot42:REDACTED" in record.getMessage()


def test_uvicorn_access_args_keep_their_shape():
    import logging

    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:5", "GET", "/ws?token=abc", "1.1", 200), None)
    RedactTokens().filter(record)
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)
    assert "abc" not in line and "token=REDACTED" in line
