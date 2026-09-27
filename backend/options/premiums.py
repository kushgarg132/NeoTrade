"""Live option premiums from the user's own connected broker.

A premium source is `async (contract: Instrument) -> Optional[float]`: the
contract's last traded premium, or None if no connected broker could price
it. Kite quotes an NFO contract directly; Upstox has no NFO quote path in
this codebase, so it reads the strike off its option chain
(UpstoxAdapter.option_chain, keyed by the underlying's NSE instrument_key).
"""

import logging
from typing import Awaitable, Callable, Optional

from backend.brokers.protocol import BrokerSessionState
from backend.brokers.registry import get_broker_adapter
from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument

logger = logging.getLogger(__name__)

PremiumSource = Callable[[Instrument], Awaitable[Optional[float]]]


def _kite_source(adapter) -> PremiumSource:
    async def premium(contract: Instrument) -> Optional[float]:
        try:
            return (await adapter.quote(contract)).get("last_price") or None
        except Exception as exc:
            logger.warning("kite could not price %s: %s", contract.tradingsymbol, exc)
            return None
    return premium


def _upstox_source(adapter, master: InstrumentMaster) -> PremiumSource:
    chains: dict[tuple[str, str], list[dict]] = {}  # one chain call per underlying+expiry

    async def premium(contract: Instrument) -> Optional[float]:
        try:
            expiry = contract.expiry.date().isoformat()
            key = (contract.name, expiry)
            if key not in chains:
                underlying = await master.get("NSE", contract.name)
                if underlying is None:
                    return None
                underlying_key = (await adapter._resolve(underlying))["instrument_key"]
                chains[key] = await adapter.option_chain(underlying_key, expiry)
            leg = "put" if contract.instrument_type == "PE" else "call"
            for row in chains[key]:
                if row["strike"] == contract.strike:
                    return (row[leg] or {}).get("ltp") or None
            return None
        except Exception as exc:
            logger.warning("upstox could not price %s: %s", contract.tradingsymbol, exc)
            return None
    return premium


async def _active(broker: str, user_id: str, credentials, redis):
    try:
        adapter = await get_broker_adapter(broker, user_id, credentials, redis)
        return adapter if await adapter.state() == BrokerSessionState.ACTIVE else None
    except Exception as exc:
        logger.warning("premium source: %s unavailable for %s: %s", broker, user_id, exc)
        return None


async def live_premium_source(db, user_id: str, credentials, redis) -> Optional[PremiumSource]:
    """The first of the user's brokers with an ACTIVE session, Kite first
    (it quotes contracts directly). None when neither is connected."""
    if kite := await _active("kite", user_id, credentials, redis):
        return _kite_source(kite)
    if upstox := await _active("upstox", user_id, credentials, redis):
        return _upstox_source(upstox, InstrumentMaster(db))
    return None
