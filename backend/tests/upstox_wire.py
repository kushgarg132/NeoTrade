"""A fake Upstox for the adapter's tests, behind both HTTP clients the adapter
can use: httpx (async) and urllib3 (under the official upstox-python SDK).
The tests pin what goes over the wire and how answers map to core models, so
they hold whichever client makes a given call. Nothing here touches a network.

    wire = UpstoxWire(monkeypatch).on("GET", "/v2/portfolio/long-term-holdings", {"data": [...]})
    ... call the adapter ...
    wire.calls[-1].query / .json / .form / .headers
"""

import gzip
import json
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx
import urllib3


@dataclass
class Call:
    method: str
    url: str
    headers: dict  # lower-cased names
    body: bytes
    host: str = ""
    path: str = ""
    query: dict = field(default_factory=dict)

    def __post_init__(self):
        parts = urlsplit(self.url)
        # unquoted: "NSE_EQ|..." and "NSE_EQ%7C..." are the same path to Upstox
        self.host, self.path, self.query = parts.netloc, unquote(parts.path), dict(parse_qsl(parts.query))

    @property
    def json(self):
        return json.loads(self.body) if self.body else None

    @property
    def form(self) -> dict:
        return dict(parse_qsl(self.body.decode()))


class UpstoxWire:
    def __init__(self, monkeypatch):
        self.routes: list[tuple] = []
        self.calls: list[Call] = []
        self.is_down = False
        wire = self

        async def httpx_send(client, request, **kwargs):
            if wire.is_down:
                raise httpx.ConnectError("down", request=request)
            status, body = wire._answer(Call(request.method, str(request.url),
                                             {k.lower(): v for k, v in request.headers.items()}, request.content))
            return httpx.Response(status, content=body, request=request)

        def urllib3_urlopen(pool, method, url, redirect=True, **kwargs):
            if wire.is_down:
                raise urllib3.exceptions.MaxRetryError(pool, url, "down")
            body = kwargs.get("body") or b""
            status, data = wire._answer(Call(method, url, {k.lower(): v for k, v in (kwargs.get("headers") or {}).items()},
                                             body.encode() if isinstance(body, str) else body))
            return urllib3.HTTPResponse(body=data, status=status, reason="OK" if status < 400 else "Error",
                                        headers={"Content-Type": "application/json"}, preload_content=True)

        monkeypatch.setattr(httpx.AsyncClient, "send", httpx_send)
        monkeypatch.setattr(urllib3.PoolManager, "urlopen", urllib3_urlopen)

    def on(self, method: str, path: str, body=None, status: int = 200) -> "UpstoxWire":
        """Answer `method` on any URL whose path starts with `path`. `body` is
        JSON-able, raw bytes, or a callable(call) -> body or (status, body).
        A later route for the same prefix wins."""
        self.routes.insert(0, (method, path, body, status))
        return self

    def scrip(self, rows: list[dict], exchange: str = "NSE") -> "UpstoxWire":
        return self.on("GET", f"/market-quote/instruments/exchange/{exchange}.json.gz",
                       gzip.compress(json.dumps(rows).encode()))

    def down(self) -> "UpstoxWire":
        """Every call fails to connect, as each client reports that."""
        self.is_down = True
        return self

    def _answer(self, call: Call) -> tuple[int, bytes]:
        self.calls.append(call)
        for method, path, body, status in self.routes:
            if method in (None, call.method) and call.path.startswith(path):
                if callable(body):
                    body = body(call)
                    if isinstance(body, tuple):
                        status, body = body
                return status, body if isinstance(body, bytes) else json.dumps(body).encode()
        raise AssertionError(f"unexpected Upstox call: {call.method} {call.url}")

    def last(self, path: str) -> Call:
        return next(c for c in reversed(self.calls) if c.path.startswith(path))
