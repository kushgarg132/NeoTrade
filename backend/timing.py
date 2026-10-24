"""How long each request took on the server: a Server-Timing header on every
response (visible in the browser's network panel) and a warning log line for
any request slower than SLOW_MS, so slow pages can be traced to an endpoint."""

import logging
import time

logger = logging.getLogger(__name__)
SLOW_MS = 300


def add_timing(app) -> None:
    @app.middleware("http")
    async def timed(request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        response.headers["Server-Timing"] = f"app;dur={ms:.0f}"
        if ms > SLOW_MS:
            logger.warning("slow request %s %s %.0f ms", request.method, request.url.path, ms)
        return response
