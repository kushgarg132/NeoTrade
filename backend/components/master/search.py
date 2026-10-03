import json
import logging
from typing import Dict, List

from backend.database import get_database
from backend.instruments.master import InstrumentMaster
from backend.instruments.resolve import resolve_symbol
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)


async def resolve_company_query(query: str, with_peers: bool = False) -> Dict:
    """
    Resolves a user query (ticker or company name) to a valid instrument via
    the deterministic instrument master (see backend.instruments.resolve),
    and best-effort suggests peer companies for display.

    Returns:
        {
            "symbol": "RELIANCE",
            "peers": ["TCS", "INFY"],
            "name": "Reliance Industries Ltd"
        }

    `with_peers` adds an LLM round trip (~10s through the gateway) for the
    peer list. Off by default: no screen displays peers, and it was most of
    the time a stock search took. Only the chat agent's tool asks for it.

    Raises:
        backend.instruments.resolve.SymbolNotFoundError if `query` cannot be
        resolved to a known instrument. Callers must not fall back to
        uppercasing the raw query -- that's the exact wrong-looking-answer
        behavior this replaces.
    """
    master = InstrumentMaster(await get_database())
    instrument = await resolve_symbol(query, master)

    peers = await _find_peers(instrument.tradingsymbol, instrument.name) if with_peers else []

    return {"symbol": instrument.tradingsymbol, "name": instrument.name, "peers": peers}


async def _find_peers(symbol: str, name: str) -> List[str]:
    """Best-effort peer/competitor suggestions for display only -- these are
    not validated against the instrument master, so never treated as
    authoritative symbol resolution."""
    system, prompt = render("peers", name=name, symbol=symbol)
    try:
        response_text = await llm_service.get_completion(prompt, system_prompt=system, tier="deep")
        clean_text = response_text.replace("```json", "").replace("```", "").strip()
        peers = json.loads(clean_text)
        if isinstance(peers, list):
            return [str(p) for p in peers][:5]
    except Exception as e:
        logger.info(f"Peer lookup failed for {symbol}: {e}")
    return []
