"""BrokerAdapter over Upstox's v2 REST API -- verified 2026-09-09 against
https://upstox.com/developer/api-documentation (fetched live; no Upstox
account exists to test against for real, matching this codebase's existing
posture for Kite -- see backend/auth/kite_session.py's own docstring).

No SDK: plain httpx calls, following the pattern the settings router already
uses for the OmniRoute gateway.

Real API surface used:
- Authorize:  GET https://api.upstox.com/v2/login/authorization/dialog
  (response_type=code, client_id, redirect_uri, state) -- a redirect the
  human completes; Upstox returns a single-use `code`.
- Token:      POST https://api.upstox.com/v2/login/authorization/token,
  application/x-www-form-urlencoded, fields code/client_id/client_secret/
  redirect_uri/grant_type=authorization_code -> {"access_token": ...}.
  Valid until 3:30 AM IST the following day regardless of issue time.
- Quote:      GET https://api.upstox.com/v2/market-quote/quotes
  ?instrument_key=... , Bearer auth -> {"data": {key: {"last_price",
  "ohlc": {open,high,low,close}, "volume", ...}}}.
- Historical: GET https://api.upstox.com/v2/historical-candle/
  {instrument_key}/{interval}/{to_date}/{from_date}, dates as YYYY-MM-DD ->
  {"data": {"candles": [[iso_timestamp, open, high, low, close, volume, oi], ...]}}.
  Interval is a documented enum; only 1minute/30minute/day are verified here
  -- everything else raises rather than guessing.
- Instruments: NOT a live API call. A gzip-compressed JSON dump per exchange
  at https://assets.upstox.com/market-quote/instruments/exchange/{EXCH}.json.gz,
  refreshed daily, each row carrying instrument_key (the real query key --
  segment|ISIN, NOT the numeric exchange_token), trading_symbol,
  exchange_token, lot_size, tick_size.
- Place Order: POST https://api-hft.upstox.com/v2/order/place, Bearer auth,
  JSON body with quantity, product (I/D), order_type, transaction_type (BUY/SELL),
  validity, price, instrument_token, trigger_price, disclosed_quantity ->
  {"status": "success", "data": {"order_id": "..."}}.
- Cancel Order: DELETE https://api-hft.upstox.com/v2/order/cancel?order_id={order_id},
  Bearer auth -> {"status": "success", "data": {"order_id": "..."}}.
- Order Status: GET https://api.upstox.com/v2/order/details?order_id={order_id},
  Bearer auth -> {"data": {"status": "...", "filled_quantity": ..., "average_price": ...}}.
- Market feed: wss://api.upstox.com/v3/feed/market-data-feed, protobuf
  frames -- see backend/data/feeds/live_upstox.py.
- Positions:   GET https://api.upstox.com/v2/portfolio/short-term-positions,
  Bearer auth -> {"data": [{"trading_symbol": "...", "quantity": ...,
  "average_price": ..., "unrealised": ..., "realised": ...}]}.
- Trades:      GET https://api.upstox.com/v2/order/trades/get-trades-for-day,
  Bearer auth -> {"data": [{"exchange", "tradingsymbol", "transaction_type",
  "quantity", "order_id", "trade_id", "average_price", "exchange_timestamp",
  ...}]} (field list verified against the official SDK's TradeData model,
  2026-09-26; the timestamp's exact format is only documented as "user
  readable", so brokers/trades.py accepts more than one).

Because instrument_key (Upstox's actual query key) isn't ISIN data the
shared Instrument model carries from other brokers' sources, quote()/
history() resolve it themselves from this adapter's own cached scrip-master
lookup, keyed by tradingsymbol -- not from the Instrument object's
instrument_token, which here is Upstox's exchange_token (numeric, but not
the key Upstox's REST API actually accepts).
"""

import gzip
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from backend.brokers.expiry import ttl_seconds_until
from backend.brokers.protocol import BrokerSessionState
from backend.components.shared.models import PriceCandle
from backend.brokers.trades import parse_ist
from backend.core.models import BrokerOrderStatus, BrokerTrade, Order, Position, Side
from backend.data.feeds.live_upstox import UpstoxMarketFeed
from backend.instruments.models import Instrument

_AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
_QUOTE_URL = "https://api.upstox.com/v2/market-quote/quotes"
_HISTORY_URL = "https://api.upstox.com/v2/historical-candle/{key}/{interval}/{to_date}/{from_date}"
_SCRIP_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
_PLACE_ORDER_URL = "https://api-hft.upstox.com/v2/order/place"
_CANCEL_ORDER_URL = "https://api-hft.upstox.com/v2/order/cancel"
_ORDER_DETAILS_URL = "https://api.upstox.com/v2/order/details"
_POSITIONS_URL = "https://api.upstox.com/v2/portfolio/short-term-positions"
_TRADES_URL = "https://api.upstox.com/v2/order/trades/get-trades-for-day"

_INTERVAL_MAP = {"1m": "1minute", "30m": "30minute", "1d": "day"}
_PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 182, "1y": 365, "2y": 730, "5y": 1825}
_PRODUCT_MAP = {"MIS": "I", "CNC": "D"}
_PRODUCT_FROM_UPSTOX = {v: k for k, v in _PRODUCT_MAP.items()}

logger = logging.getLogger(__name__)


class UpstoxAdapter:
    def __init__(
        self, api_key: Optional[str], api_secret: Optional[str], redirect_uri: Optional[str],
        redis, user_id: str,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._redirect_uri = redirect_uri
        self._redis = redis
        self._key = f"broker:{user_id}:upstox:access_token"
        self._scrip_cache: dict[str, dict[tuple, dict]] = {}

    async def state(self) -> BrokerSessionState:
        if not self._api_key or not self._api_secret:
            return BrokerSessionState.UNCONFIGURED
        token = await self.get_access_token()
        return BrokerSessionState.ACTIVE if token else BrokerSessionState.NEEDS_LOGIN

    async def login_url(self) -> Optional[str]:
        if not self._api_key:
            raise RuntimeError("Cannot generate Upstox login URL: client id is not configured")
        return str(httpx.URL(_AUTHORIZE_URL, params={
            "response_type": "code", "client_id": self._api_key, "redirect_uri": self._redirect_uri,
        }))

    async def connect(self, **fields: str) -> str:
        if not self._api_key or not self._api_secret:
            raise RuntimeError("Cannot connect to Upstox: client id/secret not configured")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_TOKEN_URL, data={
                "code": fields["request_token"], "client_id": self._api_key,
                "client_secret": self._api_secret, "redirect_uri": self._redirect_uri,
                "grant_type": "authorization_code",
            })
            resp.raise_for_status()

        access_token = resp.json()["access_token"]
        now = datetime.now(timezone.utc)
        await self._redis.set(self._key, access_token, ex=ttl_seconds_until(now, hour=3, minute=30))
        return access_token

    async def get_access_token(self) -> Optional[str]:
        return await self._redis.get(self._key)

    async def disconnect(self) -> None:
        await self._redis.delete(self._key)

    async def _load_scrip(self, exchange: str) -> dict:
        if exchange in self._scrip_cache:
            return self._scrip_cache[exchange]

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(_SCRIP_URL.format(exchange=exchange))
            resp.raise_for_status()

        rows = json.loads(gzip.decompress(resp.content))
        by_symbol = {row["trading_symbol"]: row for row in rows}
        self._scrip_cache[exchange] = by_symbol
        return by_symbol

    async def _resolve(self, instrument: Instrument) -> dict:
        scrip = await self._load_scrip(instrument.exchange)
        row = scrip.get(instrument.tradingsymbol)
        if row is None:
            raise ValueError(
                f"{instrument.tradingsymbol!r} not found in Upstox's {instrument.exchange} instrument dump"
            )
        return row

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def quote(self, instrument: Instrument) -> dict:
        row = await self._resolve(instrument)
        token = await self.get_access_token()

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _QUOTE_URL, params={"instrument_key": row["instrument_key"]}, headers=self._headers(token),
            )
            resp.raise_for_status()

        data = next(iter(resp.json()["data"].values()))
        ohlc = data.get("ohlc", {})
        return {
            "symbol": instrument.tradingsymbol,
            "last_price": data["last_price"],
            "open": ohlc.get("open", data["last_price"]),
            "high": ohlc.get("high", data["last_price"]),
            "low": ohlc.get("low", data["last_price"]),
            "close": ohlc.get("close", data["last_price"]),
            "volume": data.get("volume", 0),
        }

    async def history(self, instrument: Instrument, interval: str, period: str) -> list[PriceCandle]:
        try:
            upstox_interval = _INTERVAL_MAP[interval]
        except KeyError:
            raise ValueError(
                f"Unsupported interval for Upstox: {interval!r}. Supported: {sorted(_INTERVAL_MAP)}"
            ) from None
        try:
            days = _PERIOD_DAYS[period]
        except KeyError:
            raise ValueError(f"Unsupported period for Upstox: {period!r}. Supported: {sorted(_PERIOD_DAYS)}") from None

        row = await self._resolve(instrument)
        token = await self.get_access_token()
        to_date = datetime.now(timezone.utc).date()
        from_date = to_date - timedelta(days=days)

        url = _HISTORY_URL.format(
            key=row["instrument_key"], interval=upstox_interval,
            to_date=to_date.isoformat(), from_date=from_date.isoformat(),
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers(token))
            resp.raise_for_status()

        candles = resp.json()["data"]["candles"]
        return [
            PriceCandle(
                symbol=instrument.tradingsymbol, timestamp=c[0], open=c[1], high=c[2],
                low=c[3], close=c[4], adj_close=c[4], volume=c[5],
            )
            for c in candles
        ]

    async def instruments(self, exchanges: tuple[str, ...] = ("NSE",)) -> list[Instrument]:
        result = []
        for exchange in exchanges:
            scrip = await self._load_scrip(exchange)
            for row in scrip.values():
                result.append(Instrument(
                    exchange=row["exchange"], tradingsymbol=row["trading_symbol"], name=row["name"],
                    instrument_token=int(row["exchange_token"]), exchange_token=int(row["exchange_token"]),
                    instrument_type=row["instrument_type"], segment=row["segment"],
                    lot_size=int(row["lot_size"]), tick_size=float(row["tick_size"]),
                    isin=row.get("isin"),
                ))
        return result

    async def ticker_feed(self, instruments, timeframe, timeframe_seconds):
        token = await self.get_access_token()
        if not self._api_key or not self._api_secret or not token:
            return None

        # The feed subscribes by instrument_key; bars go out under each
        # instrument's own instrument_token, whatever source it came from.
        token_for_key = {}
        for instrument in instruments:
            try:
                row = await self._resolve(instrument)
            except ValueError as exc:
                logger.warning("upstox feed: skipping %s", exc)
                continue
            token_for_key[row["instrument_key"]] = instrument.instrument_token
        if not token_for_key:
            return None

        return UpstoxMarketFeed(
            token, token_for_key, timeframe=timeframe, timeframe_seconds=timeframe_seconds,
        )

    @staticmethod
    def _map_status(raw_status: str) -> str:
        status = raw_status.lower()
        if status == "complete":
            return "FILLED"
        if status == "rejected":
            return "REJECTED"
        if status == "cancelled":
            return "CANCELLED"
        return "ACKNOWLEDGED"

    async def place_order(self, order: Order) -> str:
        row = await self._resolve(Instrument(
            exchange="NSE", tradingsymbol=order.symbol, name=order.symbol,
            instrument_token=0, exchange_token=0, instrument_type="EQ",
            segment="NSE_EQ", lot_size=1, tick_size=0.05,
        ))
        token = await self.get_access_token()

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_PLACE_ORDER_URL, json={
                "quantity": order.whole_quantity(),
                "product": _PRODUCT_MAP[order.product],
                "order_type": order.order_type,
                "transaction_type": order.side.value,
                "validity": "DAY",
                "price": 0,
                "instrument_token": row["instrument_key"],
                "trigger_price": 0,
                "disclosed_quantity": 0,
            }, headers=self._headers(token))
            resp.raise_for_status()

        return resp.json()["data"]["order_id"]

    async def cancel_order(self, broker_order_id: str) -> None:
        token = await self.get_access_token()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{_CANCEL_ORDER_URL}?order_id={broker_order_id}", headers=self._headers(token),
            )
            resp.raise_for_status()

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        token = await self.get_access_token()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _ORDER_DETAILS_URL, params={"order_id": broker_order_id}, headers=self._headers(token),
            )
            resp.raise_for_status()

        data = resp.json()["data"]
        return BrokerOrderStatus(
            broker_order_id=broker_order_id,
            status=self._map_status(data["status"]),
            filled_quantity=float(data.get("filled_quantity", 0) or 0),
            average_price=float(data.get("average_price", 0.0) or 0),
        )

    async def get_positions(self) -> dict[str, Position]:
        token = await self.get_access_token()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_POSITIONS_URL, headers=self._headers(token))
            resp.raise_for_status()

        return {
            row["trading_symbol"]: Position(
                symbol=row["trading_symbol"],
                quantity=float(row.get("quantity", 0) or 0),
                avg_price=float(row.get("average_price", 0) or 0),
                realized_pnl=float(row.get("realised", 0.0) or 0),
                unrealized_pnl=float(row.get("unrealised", 0.0) or 0),
                # Upstox segments carry a suffix ("NSE_EQ", "NSE_FO"); "NSE" alone is the
                # cash market only, so an F&O row never looks like one.
                exchange="NSE" if row.get("exchange") in ("NSE", "NSE_EQ") else row.get("exchange"),
                product=_PRODUCT_FROM_UPSTOX.get(row.get("product")),
            )
            for row in resp.json()["data"]
        }

    async def get_trades(self) -> list[BrokerTrade]:
        token = await self.get_access_token()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_TRADES_URL, headers=self._headers(token))
            resp.raise_for_status()

        return [
            BrokerTrade(
                trade_id=str(row["trade_id"]), order_id=str(row.get("order_id") or ""),
                symbol=row.get("tradingsymbol") or row["trading_symbol"],
                exchange=row.get("exchange") or "NSE", side=Side(row["transaction_type"]),
                quantity=float(row["quantity"]), price=float(row["average_price"]),
                traded_at=parse_ist(row.get("exchange_timestamp") or row["order_timestamp"]),
            )
            for row in resp.json().get("data") or []
        ]
