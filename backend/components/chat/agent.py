from typing import Annotated, List, Dict, Any, TypedDict
import operator
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from backend.llm import llm_service
from backend.agents.tools import fetch_news_tool, fetch_stock_info_tool, fetch_price_history_tool, resolve_symbol_tool
import logging

logger = logging.getLogger(__name__)

class ChatAgent:
    def __init__(self):
        self.tools = [fetch_news_tool, fetch_stock_info_tool, fetch_price_history_tool, resolve_symbol_tool]

    async def _build_agent(self):
        """Built fresh per call, not cached on self: llm_service.get_llm()
        reads the deployment-wide model (or a per-user override, see
        backend/llm.py's use_model) on every call, so a change takes effect
        on the next message instead of needing a restart."""
        llm = await llm_service.get_llm()
        if not llm:
            logger.warning("ChatAgent: No LLM available (API Key missing?)")
            return None
        return create_react_agent(llm, self.tools)

    async def stream_message(self, message: str, history: List[Dict[str, str]] = []):
        agent = await self._build_agent()
        if not agent:
            yield {"type": "content", "data": "I am unable to function because the LLM service is not available. Please check API keys."}
            return

        messages = []
        for h in history:
            if h.get('role') == 'user':
                messages.append(HumanMessage(content=h.get('content')))
            elif h.get('role') == 'assistant':
                messages.append(AIMessage(content=h.get('content')))
        
        messages.append(HumanMessage(content=message))
        
        try:
            logger.info(f"ChatAgent streaming: {message}")
            async for event in agent.astream_events({"messages": messages}, version="v1"):
                kind = event["event"]
                
                if kind == "on_tool_start":
                    # Tool starting - show as "Thinking"
                    yield {
                        "type": "thinking", 
                        "data": f"Using tool: {event['name']}..."
                    }
                elif kind == "on_tool_end":
                    # Tool finished
                    yield {
                        "type": "thinking",
                        "data": f"Tool finished."
                    }
                elif kind == "on_chat_model_stream":
                    # The final answer streaming content
                    chunk = event["data"]["chunk"]
                    content = chunk.content
                    if isinstance(content, list):
                        # Handle list content (e.g. from Gemini)
                        content = "".join([part.get('text', '') for part in content if isinstance(part, dict) and 'text' in part])
                    
                    if content:
                        yield {"type": "content", "data": str(content)}
                        
        except Exception as e:
            logger.error(f"ChatAgent error: {e}")
            yield {"type": "content", "data": f"I encountered an error processing your request: {str(e)}"}

    async def processed_message(self, message: str, history: List[Dict[str, str]] = []) -> str:
        agent = await self._build_agent()
        if not agent:
            return "I am unable to function because the LLM service is not available. Please check API keys."

        # Convert history format if needed, but for now assuming ephemeral stateless or passed history
        # We will create a fresh state with history + new message
        
        messages = []
        for h in history:
            if h.get('role') == 'user':
                messages.append(HumanMessage(content=h.get('content')))
            elif h.get('role') == 'assistant':
                messages.append(AIMessage(content=h.get('content')))
        
        messages.append(HumanMessage(content=message))
        
        # Invoke agent
        # The prebuilt react agent returns a dictionary with 'messages'
        try:
            logger.info(f"ChatAgent receiving: {message}")
            result = await agent.ainvoke({"messages": messages})
            
            # The last message should be the AI's final answer
            last_msg = result['messages'][-1]
            content = last_msg.content
            if isinstance(content, list):
                # Handle list content (e.g. from Gemini)
                return "".join([part.get('text', '') for part in content if isinstance(part, dict) and 'text' in part])
            return str(content)
        except Exception as e:
            logger.error(f"ChatAgent error: {e}")
            return f"I encountered an error processing your request: {str(e)}"

chat_agent = ChatAgent()
