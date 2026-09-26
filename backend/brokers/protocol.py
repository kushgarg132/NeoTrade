"""The one interface every broker plugs into: credential/token lifecycle,
market data, and (later, Phase 5) order placement.

Two real shapes exist for "connect": Kite and Upstox are OAuth-style
redirects (a login_url, then a short-lived code exchanged for an access
token). Angel One is direct credential submission (client code + password +
a TOTP the user's own authenticator app generates, no redirect at all). Both
collapse onto `login_url()` (returns None when there's nothing to redirect
to) and `connect(**fields)` (takes whatever that broker's flow needs).

`BrokerSessionState` is `KiteSessionState` under this name -- the four states
(UNCONFIGURED/NEEDS_LOGIN/ACTIVE/DEGRADED) were never Kite-specific in
meaning, so it is reused rather than duplicated. Left defined in
kite_session.py rather than moved here, to avoid touching that module's
already-covered tests for a rename with no behavioral change.
"""

from typing import Optional, Protocol

from backend.auth.kite_session import KiteSessionState as BrokerSessionState
from backend.components.shared.models import PriceCandle
from backend.core.models import BrokerOrderStatus, BrokerTrade, Order, Position
from backend.engine.protocols import DataFeed
from backend.instruments.models import Instrument

__all__ = ["BrokerSessionState", "BrokerAdapter"]


class BrokerAdapter(Protocol):
    async def state(self) -> BrokerSessionState: ...

    async def login_url(self) -> Optional[str]:
        """None for a broker whose connect flow has no redirect step."""
        ...

    async def connect(self, **fields: str) -> str:
        """Completes whichever flow this broker uses and returns the access
        token. `fields` is broker-specific: Kite/Upstox expect
        `request_token`; Angel One expects `password` and `totp`."""
        ...

    async def get_access_token(self) -> Optional[str]: ...

    async def disconnect(self) -> None: ...

    async def history(self, instrument: Instrument, interval: str, period: str) -> list[PriceCandle]: ...

    async def quote(self, instrument: Instrument) -> dict: ...

    async def instruments(self, exchanges: tuple[str, ...] = ("NSE",)) -> list[Instrument]:
        """This broker's own tradable-instrument dump, in this app's shared
        `Instrument` shape. Used to refresh the instrument master and, for
        adapters whose quote/history calls need a broker-native key the
        shared master doesn't carry, to resolve one internally."""
        ...

    async def ticker_feed(
        self, instruments: list[Instrument], timeframe: str, timeframe_seconds: float
    ) -> Optional[DataFeed]:
        """Bars from the feed carry each instrument's `instrument_token`.
        None means this adapter has no live streaming support (or isn't
        ACTIVE), and the caller falls back to polling -- same as when no
        broker is connected at all."""
        ...

    async def place_order(self, order: Order) -> str:
        """Places a real MARKET order at this broker. Returns the broker's
        own order id (never this app's Order.id -- callers that need to
        correlate the two use LiveOrderStore, backend/engine/execution/
        live_order_store.py)."""
        ...

    async def cancel_order(self, broker_order_id: str) -> None: ...

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus: ...

    async def get_positions(self) -> dict[str, Position]:
        """This broker's own current-day position book, keyed by
        tradingsymbol -- the source of truth reconciliation
        (backend/routers/trading.py) merges into the local Portfolio."""
        ...

    async def get_trades(self) -> list[BrokerTrade]:
        """Today's executions from this broker's trade book. Every supported
        broker only exposes the current day here -- older history comes
        from the daily journal sync having run on those days, or from a
        CSV import (backend/journal/console_csv.py)."""
        ...
