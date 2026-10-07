"""BrokerAdapter over Zerodha Kite: pure composition of the pieces that
already exist and are already tested (KiteSessionManager, KiteProvider,
KiteInstrumentSource, KiteTickerFeed). This file adds no new Kite behavior --
it only gives them one shared shape so the rest of the app can stop
importing Kite-specific pieces directly.
"""

import asyncio
import logging
from typing import Optional

from backend.auth.kite_session import KiteSessionManager, KiteSessionState
from backend.brokers.kite_orders import KiteOrderClient
from backend.components.shared.models import PriceCandle
from backend.core.models import BrokerOrderStatus, BrokerTrade, Holding, Order, Position
from backend.data.feeds.live_kite import KiteTickerFeed
from backend.data.providers.kite_provider import KiteProvider
from backend.instruments.kite_source import KiteInstrumentSource
from backend.instruments.models import Instrument

logger = logging.getLogger(__name__)


class KiteAdapter:
    # Places NFO option orders (Order.contract) as well as NSE equity.
    supports_options = True

    def __init__(self, api_key: Optional[str], api_secret: Optional[str], redis, user_id: str) -> None:
        self._api_key = api_key
        self._session = KiteSessionManager(api_key, api_secret, redis, user_id=user_id)

    async def state(self) -> KiteSessionState:
        return await self._session.state()

    async def login_url(self) -> Optional[str]:
        return await self._session.generate_login_url()

    async def connect(self, **fields: str) -> str:
        return await self._session.exchange_request_token(fields["request_token"])

    async def get_access_token(self) -> Optional[str]:
        return await self._session.get_access_token()

    async def disconnect(self) -> None:
        await self._session.clear()

    def _client_factory(self, access_token: str):
        from kiteconnect import KiteConnect

        return lambda: KiteConnect(api_key=self._api_key, access_token=access_token)

    async def history(self, instrument: Instrument, interval: str, period: str) -> list[PriceCandle]:
        token = await self.get_access_token()
        return await KiteProvider(self._client_factory(token)).history(instrument, interval, period)

    async def quote(self, instrument: Instrument) -> dict:
        token = await self.get_access_token()
        return await KiteProvider(self._client_factory(token)).quote(instrument)

    async def instruments(self, exchanges: tuple[str, ...] = ("NSE",)) -> list[Instrument]:
        token = await self.get_access_token()
        return await KiteInstrumentSource(self._client_factory(token), exchanges=exchanges).fetch()

    async def ticker_feed(
        self, instruments: list[Instrument], timeframe: str, timeframe_seconds: float
    ) -> Optional[KiteTickerFeed]:
        if await self.state() != KiteSessionState.ACTIVE:
            return None

        from kiteconnect import KiteTicker
        from kiteconnect.exceptions import PermissionException

        token = await self.get_access_token()
        # A Kite Connect app without the market-data add-on logs in fine but
        # its WebSocket is refused (403) and the feed would sit silent all
        # day; None lets build_feed fall through to the next broker.
        try:
            probe = f"{instruments[0].exchange}:{instruments[0].tradingsymbol}" if instruments else "NSE:INFY"
            await asyncio.to_thread(self._client_factory(token)().ltp, [probe])
        except PermissionException:
            logger.warning("kite app has no market-data permission: no tick feed")
            return None
        return KiteTickerFeed(
            lambda: KiteTicker(api_key=self._api_key, access_token=token),
            [i.instrument_token for i in instruments], timeframe=timeframe, timeframe_seconds=timeframe_seconds,
        )

    async def place_order(self, order: Order) -> str:
        token = await self.get_access_token()
        return await KiteOrderClient(self._client_factory(token)).place_order(order)

    async def cancel_order(self, broker_order_id: str) -> None:
        token = await self.get_access_token()
        await KiteOrderClient(self._client_factory(token)).cancel_order(broker_order_id)

    async def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        token = await self.get_access_token()
        return await KiteOrderClient(self._client_factory(token)).get_order_status(broker_order_id)

    async def get_positions(self) -> dict[str, Position]:
        token = await self.get_access_token()
        return await KiteOrderClient(self._client_factory(token)).get_positions()

    async def get_holdings(self) -> list[Holding]:
        token = await self.get_access_token()
        return await KiteOrderClient(self._client_factory(token)).get_holdings()

    async def get_trades(self) -> list[BrokerTrade]:
        token = await self.get_access_token()
        return await KiteOrderClient(self._client_factory(token)).get_trades()
