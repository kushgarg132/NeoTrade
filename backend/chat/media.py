"""Chat tools that show the user something rather than return text: a chart
drawn from real numbers (the widget renders it with recharts) and an
AI-generated image (OmniRoute /images/generations). Each tool drops its
payload into `sink`; the agent turns it into a `chart` or `image` event, so
image bytes never enter the model's context."""

import logging
from typing import Literal, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.configs.settings import settings
from backend.llm import llm_service

logger = logging.getLogger(__name__)

MAX_POINTS = 400
MAX_SERIES = 6


class Series(BaseModel):
    name: str = Field(description="Legend label, e.g. 'RELIANCE' or 'Portfolio'")
    values: list[Optional[float]] = Field(description="One number per label, in the same order; null for a gap")


def chart_spec(title: str, kind: str, labels: list[str], series: list, unit: str = "") -> dict:
    """Validates and normalises a chart; raises ValueError with a reason the model can act on."""
    series = [s if isinstance(s, Series) else Series(**s) for s in series]
    if not labels or not series:
        raise ValueError("a chart needs labels and at least one series")
    if len(labels) > MAX_POINTS or len(series) > MAX_SERIES:
        raise ValueError(f"at most {MAX_POINTS} labels and {MAX_SERIES} series; aggregate first")
    for s in series:
        if len(s.values) != len(labels):
            raise ValueError(f"series '{s.name}' has {len(s.values)} values for {len(labels)} labels")
    if kind == "pie" and len(series) != 1:
        raise ValueError("a pie chart takes exactly one series")
    return {"title": title[:120], "kind": kind, "unit": unit[:12],
            "labels": [str(label)[:40] for label in labels],
            "series": [{"name": s.name[:40], "values": s.values} for s in series]}


async def _generate(prompt: str) -> str:
    """Returns a data: URL for one image of `prompt`."""
    keys = llm_service.keys_for("chat")
    if not keys:
        raise RuntimeError("the AI gateway is not configured")
    await llm_service._charge("chat")  # counts against the user's daily LLM ceiling
    url = settings.OMNIROUTE_BASE_URL.rstrip("/") + "/images/generations"
    async with httpx.AsyncClient(timeout=180) as client:
        res = await client.post(url, headers={"Authorization": f"Bearer {keys[0]}"},
                                json={"model": settings.OMNIROUTE_IMAGE_MODEL, "prompt": prompt, "n": 1})
        res.raise_for_status()
        item = (res.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            return "data:image/png;base64," + item["b64_json"]
        if item.get("url"):
            return item["url"]
    raise RuntimeError("the image model returned no image")


def media_tools(sink: list) -> list:
    async def make_chart(title: str, kind: Literal["line", "bar", "area", "pie"], labels: list[str],
                         series: list[Series], unit: str = "") -> str:
        try:
            sink.append({"type": "chart", "data": chart_spec(title, kind, labels, series, unit)})
        except ValueError as exc:
            return f"Chart refused: {exc}"
        return "The chart is shown to the user above your reply. Do not repeat its numbers as a table."

    async def generate_image(prompt: str) -> str:
        if not settings.OMNIROUTE_IMAGE_MODEL:
            return "Image generation is switched off on this server."
        try:
            sink.append({"type": "image", "data": {"url": await _generate(prompt), "alt": prompt[:200]}})
        except Exception as exc:
            logger.warning("chat image generation failed: %s", exc)
            return "Image generation failed; tell the user and offer a make_chart instead if it was data."
        return "The image is shown to the user above your reply."

    return [
        StructuredTool.from_function(coroutine=make_chart, name="make_chart", description=(
            "Draw a chart for the user from real numbers you already fetched with the other tools "
            "(price history, portfolio, journal, query_my_data). Use it for every graph, trend, comparison "
            "or breakdown. labels are the x-axis (dates as YYYY-MM-DD, or category names); each series has "
            "one value per label. kind: line for prices/trends over time, area for cumulative P&L or value, "
            "bar for comparing categories or periods, pie for a single breakdown (allocation, sector mix). "
            "unit: '₹' or '%' or ''. Never invent numbers.")),
        StructuredTool.from_function(coroutine=generate_image, name="generate_image", description=(
            "Generate an illustrative image (a concept diagram, an icon, a visual explainer) from a text "
            "description. Never use it for charts of data: its numbers would be made up; use make_chart.")),
    ]
