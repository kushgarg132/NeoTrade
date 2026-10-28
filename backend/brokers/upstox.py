"""BrokerAdapter over Upstox's v2/v3 REST API, through the official
upstox-python SDK (upstox_client, pinned in requirements.txt). No Upstox
account exists to test against for real; tests/test_upstox_adapter.py pins
every request and mapping at the wire.

The SDK is synchronous (urllib3), so each call runs in a worker thread
(`_call`), on one SDK client per access token. Two calls stay on httpx:
the quote (the SDK sends `?symbol=`, this API documents `?instrument_key=`)
and the instrument dumps (static files, not an API the SDK wraps).

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
- Historical: GET https://api.upstox.com/v3/historical-candle/
  {instrument_key}/{unit}/{n}/{to_date}/{from_date}, dates as YYYY-MM-DD ->
  {"data": {"candles": [[iso_timestamp, open, high, low, close, volume, oi], ...]}},
  newest first. Verified 2026-10-07: minutes/5 back to Oct 2025, free; a minute
  range over a month is refused (UDAPI1148 "Invalid date range"), so minute
  history is fetched in 28-day chunks. Unmapped intervals raise rather than guess.
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

- Holdings:    GET https://api.upstox.com/v2/portfolio/long-term-holdings,
  Bearer auth -> {"data": [{"isin", "company_name", "tradingsymbol",
  "trading_symbol", "exchange", "quantity", "t1_quantity", "average_price",
  "last_price", "close_price", ...}]} (the official SDK's PortfolioApi and
  HoldingsData model, 2026-09-27). ponytail: `quantity` is taken as the
  whole holding; whether it already includes t1_quantity is not stated
  there -- check against a real account. No mutual fund holdings API.
- Option contracts: GET https://api.upstox.com/v2/option/contract
  ?instrument_key={underlying}[&expiry_date=YYYY-MM-DD], Bearer auth ->
  {"data": [{"expiry", "strike_price", "lot_size", "instrument_type",
  "instrument_key", "trading_symbol", "weekly", ...}]}.
- Option chain: GET https://api.upstox.com/v2/option/chain
  ?instrument_key={underlying}&expiry_date=YYYY-MM-DD (both required),
  Bearer auth -> {"data": [{"expiry", "pcr", "strike_price",
  "underlying_key", "underlying_spot_price", "call_options"/"put_options":
  {"instrument_key", "market_data": {ltp, volume, oi, close_price,
  bid_price, bid_qty, ask_price, ask_qty, prev_oi}, "option_greeks":
  {vega, theta, gamma, delta, iv, pop}}}]}. Underlying keys for the indices
  are "NSE_INDEX|Nifty 50" and "NSE_INDEX|Nifty Bank". Both verified
  2026-09-27 against the official SDK's generated OptionsApi and models
  (upstox/upstox-python on GitHub); upstox.com itself was not reachable.

Because instrument_key (Upstox's actual query key) isn't ISIN data the
shared Instrument model carries from other brokers' sources, quote()/
history() resolve it themselves from this adapter's own cached scrip-master
lookup, keyed by tradingsymbol -- not from the Instrument object's
instrument_token, which here is Upstox's exchange_token (numeric, but not
the key Upstox's REST API actually accepts).
"""

import asyncio
import gzip
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import httpx
import upstox_client
import urllib3
from upstox_client.rest import ApiException

from backend.brokers.expiry import ttl_seconds_until
from backend.brokers.protocol import BrokerSessionState, keyed_positions
from backend.core.models import PriceCandle
from backend.brokers.trades import parse_ist
from backend.brokers.holdings import kind_of
from backend.core.models import BrokerOrderStatus, BrokerTrade, Holding, Order, Position, Side
from backend.data.feeds.live_upstox import UpstoxMarketFeed
from backend.instruments.models import Instrument

_AUTHORIZE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
_QUOTE_URL = "https://api.upstox.com/v2/market-quote/quotes"
_SCRIP_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
_API_VERSION = "2.0"
# Past trades by date range (PostTradeApi.get_trades_by_date_range); not yet
# called against a real account.
_TRADE_HISTORY_PAGE_SIZE = 100

_INTERVAL_MAP = {"1m": ("minutes", 1), "5m": ("minutes", 5), "15m": ("minutes", 15),
                 "30m": ("minutes", 30), "1d": ("days", 1)}
# HistoricalFeed asks for "max" on intraday timeframes: past the gate's 372-day ask
# (risk/backtest_gate.py::LOOKBACK_DAYS), so the span is a full year.
_PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 182, "1y": 365, "2y": 730, "5y": 1825, "max": 400}
# v3 refuses a minute range over a month ("Invalid date range"); days take a decade.
_CHUNK_DAYS = {"minutes": 28, "days": 3650}
_RETRIES_429 = 4
# Spacing between history calls, per process: a year of 5-minute bars for the
# gate's 75 names is ~975 calls, and Upstox counts per second, minute and
# half hour (2,000). 0.5 s keeps under all three; a 429 still backs off.
_HISTORY_SPACING = 0.5
_history_lock = asyncio.Lock()
_history_last = [0.0]


async def _space_history_call() -> None:
    async with _history_lock:
        wait = _history_last[0] + _HISTORY_SPACING - asyncio.get_running_loop().time()
        if wait > 0:
            await asyncio.sleep(wait)
        _history_last[0] = asyncio.get_running_loop().time()
_PRODUCT_FROM_UPSTOX = {"I": "MIS", "D": "CNC"}
# "D" is delivery for equity and carry-forward for F&O, so NRML maps there too.
_PRODUCT_MAP = {"MIS": "I", "CNC": "D", "NRML": "D"}

logger = logging.getLogger(__name__)


class UpstoxHTTPError(httpx.HTTPError):
    """A failed SDK call. An httpx.HTTPError, so callers handle SDK and httpx
    calls alike (the options router answers 502 for either)."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


@lru_cache(maxsize=8)
def _sdk_client(token: str) -> "upstox_client.ApiClient":
    # ponytail: one SDK client per live token, each with its own idle thread
    # pool; 8 covers this deployment's users, raise it if more trade at once.
    config = upstox_client.Configuration()
    config.access_token = token
    client = upstox_client.ApiClient(config)
    # Default headers beat the SDK's per-call Accept (some methods send */*),
    # and carry the session to calls the SDK sends without one (v3 history),
    # as this adapter always has.
    client.set_default_header("Accept", "application/json")
    if token:
        client.set_default_header("Authorization", f"Bearer {token}")
    return client


class UpstoxAdapter:
    # place_order sends order_type and limit_price through (backend/chat/actions.py checks this).
    SUPPORTS_LIMIT = True
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

        access_token = (await self._call(
            "LoginApi", "token", _API_VERSION, token="", code=fields["request_token"], client_id=self._api_key,
            client_secret=self._api_secret, redirect_uri=self._redirect_uri, grant_type="authorization_code",
        ))["access_token"]
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

    async def _call(self, api: str, method: str, *args, token: Optional[str] = None, timeout: float = 10.0,
                    **kwargs) -> dict:
        """One SDK call, off the event loop; the response as a plain dict.
        `token` defaults to this user's session ("" sends no Bearer)."""
        if token is None:
            token = await self.get_access_token() or ""
        call = getattr(getattr(upstox_client, api)(_sdk_client(token)), method)
        try:
            response = await asyncio.to_thread(call, *args, _request_timeout=timeout, **kwargs)
        except ApiException as exc:
            raise UpstoxHTTPError(f"Upstox {method} failed: HTTP {exc.status} {exc.reason}", exc.status) from None
        except urllib3.exceptions.HTTPError as exc:
            raise UpstoxHTTPError(f"Upstox {method} failed: {type(exc).__name__}") from None
        return response.to_dict()

    async def option_expiries(self, underlying_key: str) -> list[str]:
        """Every listed expiry for `underlying_key`, soonest first, as
        YYYY-MM-DD -- read from the exchange's own contract list rather than
        computed, so an expiry-day change never needs a code change."""
        rows = (await self._call("OptionsApi", "get_option_contracts", underlying_key, timeout=15.0))["data"] or []
        return sorted({str(row["expiry"])[:10] for row in rows if row.get("expiry")})

    async def option_chain(self, underlying_key: str, expiry: str) -> list[dict]:
        """One row per strike, lowest first, with the call and the put side
        by side: live premium, open interest and its change, volume, best
        bid/ask and implied volatility/greeks, straight from Upstox."""
        def side(leg: Optional[dict]) -> Optional[dict]:
            if not leg:
                return None
            market, greeks = leg.get("market_data") or {}, leg.get("option_greeks") or {}
            return {
                "instrument_key": leg.get("instrument_key"),
                "ltp": market.get("ltp"),
                "close": market.get("close_price"),
                "oi": market.get("oi"),
                "oi_change": (market.get("oi") or 0) - (market.get("prev_oi") or 0),
                "volume": market.get("volume"),
                "bid": market.get("bid_price"),
                "ask": market.get("ask_price"),
                "iv": greeks.get("iv"),
                "delta": greeks.get("delta"),
                "theta": greeks.get("theta"),
            }

        rows = (await self._call("OptionsApi", "get_put_call_option_chain", underlying_key, expiry,
                                 timeout=15.0))["data"] or []
        return sorted(
            (
                {
                    "strike": row["strike_price"],
                    "spot": row.get("underlying_spot_price"),
                    "pcr": row.get("pcr"),
                    "call": side(row.get("call_options")),
                    "put": side(row.get("put_options")),
                }
                for row in rows
            ),
            key=lambda row: row["strike"],
        )

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
        token = await self.get_access_token() or ""
        unit, n = upstox_interval
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        candles = []
        while end > start:
            chunk_from = max(start, end - timedelta(days=_CHUNK_DAYS[unit]))
            for attempt in range(_RETRIES_429 + 1):
                await _space_history_call()
                try:
                    # v3: any minute interval (v2 had only 1m and 30m), from Jan 2022, free.
                    body = await self._call("HistoryV3Api", "get_historical_candle_data1", row["instrument_key"],
                                            unit, n, end.isoformat(), chunk_from.isoformat(), token=token, timeout=20.0)
                    break
                except UpstoxHTTPError as exc:
                    if exc.status != 429 or attempt == _RETRIES_429:
                        raise
                await asyncio.sleep(2 ** attempt)  # per-second/minute limits: back off
            candles += body["data"]["candles"]
            end = chunk_from - timedelta(days=1)

        candles.sort(key=lambda c: c[0])  # Upstox answers newest first
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
                # The NSE dump also carries F&O, commodity and index rows, all
                # labelled exchange "NSE"; indices have no lot_size, and one
                # KeyError dropped the whole refresh (seen 2026-10-16).
                if row.get("segment") != f"{exchange}_EQ":
                    continue
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

        # Mid-run adds (plan/expand.py) look up the scrip dumps already loaded above.
        def key_for(instrument):
            return self._scrip_cache.get(instrument.exchange, {}).get(instrument.tradingsymbol, {}).get("instrument_key")

        return UpstoxMarketFeed(
            token, token_for_key, timeframe=timeframe, timeframe_seconds=timeframe_seconds, key_for=key_for,
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

    # Places option orders too: the contract's instrument_key comes off the
    # option chain (see _option_key).
    supports_options = True

    async def _option_key(self, contract: Instrument) -> str:
        """Upstox's instrument_key for a contract from Kite's NFO dump. The
        two brokers spell option symbols differently, so it is matched by
        underlying, expiry, strike and CE/PE on Upstox's own option chain,
        whose legs carry their instrument_key (verified against the SDK's
        models, like option_chain itself). Refuses rather than guesses."""
        underlying = await self._resolve(Instrument(
            exchange="NSE", tradingsymbol=contract.name, name=contract.name,
            instrument_token=0, exchange_token=0, instrument_type="EQ",
            segment="NSE_EQ", lot_size=1, tick_size=0.05,
        ))
        leg = "put" if contract.instrument_type == "PE" else "call"
        for row in await self.option_chain(underlying["instrument_key"], contract.expiry.date().isoformat()):
            if row["strike"] == contract.strike and (row[leg] or {}).get("instrument_key"):
                return row[leg]["instrument_key"]
        raise ValueError(f"{contract.tradingsymbol!r} not found on Upstox's option chain")

    async def place_order(self, order: Order) -> str:
        if order.contract is not None:
            instrument_key = await self._option_key(order.contract)
        else:
            instrument_key = (await self._resolve(Instrument(
                exchange="NSE", tradingsymbol=order.symbol, name=order.symbol,
                instrument_token=0, exchange_token=0, instrument_type="EQ",
                segment="NSE_EQ", lot_size=1, tick_size=0.05,
            )))["instrument_key"]
        body = upstox_client.PlaceOrderRequest(
            quantity=order.whole_quantity(), product=_PRODUCT_MAP[order.product], order_type=order.order_type,
            transaction_type=order.side.value, validity="DAY", price=order.limit_price or 0,
            instrument_token=instrument_key, trigger_price=order.trigger_price or 0, disclosed_quantity=0,
            is_amo=False,  # the SDK model requires it; false is the API's own default
        )
        return (await self._call("OrderApi", "place_order", body, _API_VERSION))["data"]["order_id"]

    async def cancel_order(self, broker_order_id: str) -> None:
        await self._call("OrderApi", "cancel_order", broker_order_id, _API_VERSION)

    async def modify_order(self, broker_order_id: str, quantity: Optional[int] = None, price: Optional[float] = None,
                           trigger_price: Optional[float] = None) -> None:
        current = next((o for o in await self.get_orders() if o["order_id"] == broker_order_id), None)
        if current is None:
            raise ValueError(f"No order {broker_order_id} at Upstox")
        await self._call("OrderApi", "modify_order", upstox_client.ModifyOrderRequest(
            order_id=broker_order_id, validity="DAY", disclosed_quantity=0,
            quantity=quantity or int(current["quantity"]),
            price=price if price is not None else current["price"],
            trigger_price=trigger_price if trigger_price is not None else current["trigger_price"],
            order_type=current.get("order_type") or ("LIMIT" if (price or current["price"]) else "MARKET"),
        ), _API_VERSION)

    async def get_orders(self) -> list[dict]:
        """Today's order book, normalised."""
        return [{
            "order_id": o.get("order_id"), "symbol": o.get("trading_symbol") or o.get("tradingsymbol"),
            "side": o.get("transaction_type"), "quantity": float(o.get("quantity") or 0),
            "price": float(o.get("price") or 0), "trigger_price": float(o.get("trigger_price") or 0),
            "order_type": o.get("order_type"), "status": o.get("status"),
        } for o in (await self._call("OrderApi", "get_order_book", _API_VERSION))["data"] or []]

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        # The SDK's get_order_details is /order/history; /order/details is get_order_status.
        data = (await self._call("OrderApi", "get_order_status", order_id=broker_order_id))["data"]
        return BrokerOrderStatus(
            broker_order_id=broker_order_id,
            status=self._map_status(data["status"]),
            filled_quantity=float(data.get("filled_quantity", 0) or 0),
            average_price=float(data.get("average_price", 0.0) or 0),
        )

    async def get_positions(self) -> dict[str, Position]:
        return keyed_positions([
            Position(
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
            for row in (await self._call("PortfolioApi", "get_positions", _API_VERSION))["data"] or []
        ])

    async def get_holdings(self) -> list[Holding]:
        holdings = []
        for row in (await self._call("PortfolioApi", "get_holdings", _API_VERSION))["data"] or []:
            symbol = row.get("trading_symbol") or row.get("tradingsymbol")
            quantity = float(row.get("quantity") or 0)
            if not symbol or quantity <= 0:
                continue
            holdings.append(Holding(
                symbol=symbol, isin=row.get("isin"), name=row.get("company_name"),
                exchange=row.get("exchange"), kind=kind_of(symbol), quantity=quantity,
                avg_price=float(row.get("average_price") or 0),
                last_price=row.get("last_price") or None, close_price=row.get("close_price") or None,
                broker="upstox",
            ))
        return holdings

    async def get_trade_history(self, start, end) -> list[BrokerTrade]:
        """Equity and F&O trades between two dates (inclusive). The history
        carries a date but no time, so every fill is stamped 09:15 IST that
        day: daily P&L holds, intraday order within a day does not."""
        trades = []
        for segment in ("EQ", "FO"):
            page, total = 1, 1
            while page <= total:
                body = await self._call("PostTradeApi", "get_trades_by_date_range", start.isoformat(), end.isoformat(),
                                        page, _TRADE_HISTORY_PAGE_SIZE, segment=segment, timeout=20.0)
                trades += [_history_trade(row) for row in body["data"] or []]
                total = ((body["meta_data"] or {}).get("page") or {}).get("total_pages") or 1
                page += 1
        return trades

    async def get_trades(self) -> list[BrokerTrade]:
        return [
            BrokerTrade(
                trade_id=str(row["trade_id"]), order_id=str(row.get("order_id") or ""),
                symbol=row.get("tradingsymbol") or row["trading_symbol"],
                exchange=row.get("exchange") or "NSE", side=Side(row["transaction_type"]),
                quantity=float(row["quantity"]), price=float(row["average_price"]),
                traded_at=parse_ist(row.get("exchange_timestamp") or row["order_timestamp"]),
            )
            for row in (await self._call("OrderApi", "get_trade_history", _API_VERSION))["data"] or []
        ]


_HISTORY_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y")


def _history_day(text: str):
    # ponytail: the SDK types trade_date as a bare string; formats beyond these
    # need a real response to know.
    for fmt in _HISTORY_DATE_FORMATS:
        try:
            return datetime.strptime(str(text).strip()[:11].strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized Upstox trade_date: {text!r}")


def _history_symbol(row: dict) -> str:
    """Options come back as underlying + option_type/strike/expiry; spell them
    the spaced way journal/roundtrips.instrument_kind reads ("NIFTY 25100 CE ...")."""
    symbol = row.get("symbol") or row.get("scrip_name")
    if row.get("segment") != "FO":
        return symbol
    from backend.journal.roundtrips import instrument_kind
    if instrument_kind(symbol, "") != "STOCK":
        return symbol  # already a full contract symbol
    strike = str(row.get("strike_price") or "").removesuffix(".0")
    option = (row.get("option_type") or "").upper()
    parts = [symbol, strike, option] if option in ("CE", "PE") else [symbol, "FUT"]
    return " ".join(p for p in parts + [str(row.get("expiry") or "")] if p)


def _history_trade(row: dict) -> BrokerTrade:
    day = _history_day(row["trade_date"])
    return BrokerTrade(
        trade_id=str(row["trade_id"]), order_id="", symbol=_history_symbol(row),
        exchange=row.get("exchange") or "NSE", side=Side(row["transaction_type"].upper()),
        quantity=float(row["quantity"]), price=float(row["price"]),
        traded_at=parse_ist(datetime.combine(day, datetime.min.time().replace(hour=9, minute=15))),
    )
