"""Chat tools that show the user something rather than return text: a chart
drawn from real numbers (the widget renders it with recharts; Telegram gets
`render_png`) and an AI-generated image (OmniRoute /images/generations). Each tool drops its
payload into `sink`; the agent turns it into a `chart` or `image` event, so
image bytes never enter the model's context."""

import io
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


# The app's dark theme (frontend/src/index.css) so a Telegram chart looks like the widget's.
BG, INK, MUTED, GRID = "#141416", "#ececf1", "#9a9aa6", "#2a2a30"
PALETTE = ["#f472b6", "#22c55e", "#60a5fa", "#f59e0b", "#a78bfa", "#ef4444"]


def render_png(spec: dict) -> bytes:
    """A `chart_spec` drawn as a PNG (matplotlib, headless) for clients that cannot draw it."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels, series, unit, kind = spec["labels"], spec["series"], spec.get("unit", ""), spec["kind"]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    try:
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(BG)
        ax.set_title(spec["title"], color=INK, fontsize=13, loc="left", pad=12)
        if kind == "pie":
            values = [max(0.0, v or 0.0) for v in series[0]["values"]]
            ax.pie(values, labels=labels, colors=PALETTE * (len(values) // len(PALETTE) + 1),
                   autopct="%1.0f%%", textprops={"color": INK, "fontsize": 9},
                   wedgeprops={"edgecolor": BG, "linewidth": 1.5})
            ax.axis("equal")
        else:
            x = range(len(labels))
            width = 0.8 / len(series)
            # An area fills down to the lowest value, not to zero: from zero a ₹1L portfolio's moves look flat.
            floor = min((v for s in series for v in s["values"] if v is not None), default=0)
            for i, s in enumerate(series):
                color = PALETTE[i % len(PALETTE)]
                y = [float("nan") if v is None else v for v in s["values"]]
                if kind == "bar":
                    ax.bar([k - 0.4 + width * (i + 0.5) for k in x], [0 if v is None else v for v in s["values"]],
                           width, label=s["name"], color=color)
                else:
                    ax.plot(x, y, label=s["name"], color=color, linewidth=2)
                    if kind == "area":
                        ax.fill_between(x, y, floor, alpha=0.18, color=color)
            step = max(1, len(labels) // 8)  # at most ~8 x labels stay readable on a phone
            ax.set_xticks(list(x)[::step], labels[::step], rotation=30 if len(labels) > 6 else 0, ha="right" if len(labels) > 6 else "center")
            if unit:
                def tick(v, _):
                    num = f"{abs(v):,.2f}".rstrip("0").rstrip(".")
                    sign = "−" if v < 0 else ""
                    return f"{sign}{num}%" if unit == "%" else f"{sign}{unit}{num}"
                ax.yaxis.set_major_formatter(tick)
            ax.tick_params(colors=MUTED, labelsize=9)
            ax.grid(axis="y", color=GRID, linewidth=0.8)
            ax.set_axisbelow(True)
            for side in ax.spines.values():
                side.set_visible(False)
            if len(series) > 1:
                ax.legend(frameon=False, labelcolor=INK, fontsize=9, loc="best")
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG)
        return buf.getvalue()
    finally:
        plt.close(fig)


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
