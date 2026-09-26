"""Research pipeline: produces a human-readable ResearchReport, nothing more.

This used to be MasterAgent (backend/components/master/agent.py) -- a
LangGraph pipeline that fanned out into QuantAgent/RiskAgent and ended in a
decision_node that emitted a BUY/SELL/HOLD signal. That made this pipeline a
second, ad hoc decision-maker sitting next to the real one (backend/strategies
+ backend/scoring, Task 3/4). This module is demoted: it resolves a query,
gathers company info + news/sentiment, and asks the LLM for a narrative
thesis (written alongside the analyst summary, one LLM call). It emits no signal and makes no trade decision -- scoring
(backend.scoring.composite) and strategies (backend.strategies) are the only
things allowed to do that now.
"""

from typing import List, Optional, Any, Dict, TypedDict
from pydantic import BaseModel, ConfigDict
import logging

from langgraph.graph import StateGraph, END

from backend.components.analyst.agent import AnalystAgent
from backend.components.master.search import resolve_company_query

logger = logging.getLogger(__name__)


class ResearchReport(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str

    # Enhanced data for UI
    company_info: Optional[Dict[str, Any]] = None

    # Sentiment
    sentiment_score: float = 0.0
    impact_score: int = 0
    sentiment: Dict[str, Any] = {}

    # News & Events
    news_articles: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    analyst_summary: str = ""
    thesis: str = ""  # LLM-synthesized narrative from synthesize_node
    peers: List[str] = []


class AgentState(TypedDict):
    symbol: str

    analyst_output: Optional[Dict[str, Any]]
    company_info: Optional[Dict[str, Any]]
    peers: List[str]
    thesis: str


class ResearchAgent:
    """Research-report-generator only. No RiskAgent, no QuantAgent, no
    decision node -- see module docstring."""

    def __init__(self):
        self.analyst = AnalystAgent()

        workflow = StateGraph(AgentState)
        workflow.add_node("resolve_query", self.resolve_node)
        workflow.add_node("company_info", self.company_info_node)
        workflow.add_node("analyst", self.analyst_node)
        workflow.add_node("synthesize_node", self.synthesize_node)

        workflow.set_entry_point("resolve_query")
        workflow.add_edge("resolve_query", "company_info")
        workflow.add_edge("company_info", "analyst")
        workflow.add_edge("analyst", "synthesize_node")
        workflow.add_edge("synthesize_node", END)

        self.graph = workflow.compile()

    # --- Nodes ---
    async def resolve_node(self, state: AgentState):
        query = state["symbol"]
        logger.info(f"Resolving query: {query}")
        # resolve_company_query already routes through
        # backend.instruments.resolve.resolve_symbol (Task 1's deterministic
        # instrument master) -- no duplicate resolution logic here.
        resolved_data = await resolve_company_query(query)
        logger.info(f"Resolved to: {resolved_data}")

        return {
            "symbol": resolved_data["symbol"],
            "peers": resolved_data.get("peers", []),
        }

    async def company_info_node(self, state: AgentState):
        logger.info("Fetching company info...")
        try:
            from backend.components.master.stock_info import fetch_stock_info_logic
            info_obj = await fetch_stock_info_logic(state["symbol"])
            return {"company_info": info_obj.model_dump(mode="json")}
        except Exception as e:
            logger.warning(f"Failed to fetch company info: {e}")
            return {"company_info": None}

    async def analyst_node(self, state: AgentState):
        result = await self.analyst.analyze(state)
        return {"analyst_output": result}

    async def synthesize_node(self, state: AgentState):
        """The thesis is written in the same LLM call as the analyst's
        summary (backend/components/analyst/agent.py) -- no second call."""
        return {"thesis": (state.get("analyst_output") or {}).get("thesis", "")}

    async def run(self, symbol: str) -> ResearchReport:
        inputs = {
            "symbol": symbol,
            "analyst_output": None,
            "company_info": None,
            "peers": [],
            "thesis": "",
        }

        result = await self.graph.ainvoke(inputs)
        analyst_out = result["analyst_output"]

        return ResearchReport(
            symbol=result["symbol"],
            company_info=result.get("company_info"),
            sentiment_score=analyst_out["sentiment_score"],
            impact_score=analyst_out["impact_score"],
            sentiment=analyst_out.get("sentiment_analysis", {}),
            news_articles=analyst_out["news_articles"],
            events=analyst_out["events"],
            analyst_summary=analyst_out["summary"],
            thesis=result["thesis"],
            peers=result.get("peers", []),
        )
