import json
import logging
from typing import Optional

from backend.instruments.master import InstrumentMaster
from backend.instruments.models import Instrument
from backend.llm import llm_service
from backend.prompts import render

logger = logging.getLogger(__name__)


class SymbolNotFoundError(Exception):
    """Raised when a query cannot be resolved to a known instrument. Never
    caught to fabricate a symbol -- callers should surface this as a real
    404/not-found, not silently uppercase the raw query."""


async def resolve_symbol(query: str, master: InstrumentMaster) -> Instrument:
    """Deterministic instrument resolution: exact tradingsymbol match wins
    immediately. Otherwise fall back to fuzzy search, and if that's ambiguous,
    let the LLM pick among the *returned candidates only* -- it can never
    invent a symbol that isn't already in the instrument master.
    """
    query = query.strip()
    if not query:
        raise SymbolNotFoundError("Empty query")

    for exchange in ("NSE", "BSE"):
        exact = await master.get(exchange, query)
        if exact:
            return exact

    candidates = await master.search(query, limit=10)
    if not candidates:
        raise SymbolNotFoundError(f"No instrument found for query: {query!r}")

    if len(candidates) == 1:
        return candidates[0]

    chosen = await _llm_pick(query, candidates)
    if chosen is None:
        raise SymbolNotFoundError(
            f"Ambiguous query {query!r}: {len(candidates)} candidates, "
            "LLM did not pick a valid one"
        )
    return chosen


async def _llm_pick(query: str, candidates: list[Instrument]) -> Optional[Instrument]:
    options = [{"tradingsymbol": c.tradingsymbol, "name": c.name} for c in candidates]
    system, prompt = render("resolve_instrument", query=query, candidates=json.dumps(options))
    try:
        response = await llm_service.get_completion(prompt, system_prompt=system, tier="fast", feature="research")
    except Exception as e:
        logger.warning(f"LLM resolution failed for {query!r}: {e}")
        return None

    answer = response.strip().strip('"').upper()
    by_symbol = {c.tradingsymbol.upper(): c for c in candidates}
    return by_symbol.get(answer)
