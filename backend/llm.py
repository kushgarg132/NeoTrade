
from backend.app_settings import current_llm_model, feature_enabled
from backend.configs.settings import settings
from typing import Optional, List, Any, AsyncIterator
import contextlib
import contextvars
import logging
from langchain_core.runnables import Runnable, RunnableConfig

logger = logging.getLogger(__name__)

_model_override: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "model_override", default=None
)
_billed_user: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("billed_user", default=None)
# Features a user's own request spends; the rest (news, plan, learning,
# portfolio's weekly review) is shared or scheduled work.
USER_FEATURES = {"chat", "research"}


class DailyLimitReached(Exception):
    """The user has spent today's USER_LLM_CALLS_PER_DAY."""


LIMIT_MESSAGE = "You've used today's AI allowance. It resets at midnight IST."


@contextlib.contextmanager
def use_model(model: Optional[str], user_id: Optional[str] = None):
    """Ambient per-user model override for the duration of a `with` block.
    A no-op when `model` is None, so callers with no saved preference don't
    need to branch. Every nested LLMService.get_completion call anywhere in
    the tree (ResearchAgent, AnalystAgent, sentiment/events classifiers,
    resolve_symbol, ...) picks this up transparently through get_llm() --
    no signature changes needed in any of those modules. Propagates
    correctly into a child asyncio.Task created via create_task/gather from
    inside the `with` block, since each new Task captures a copy of the
    current context at creation time."""
    token, billed = _model_override.set(model), _billed_user.set(user_id)
    try:
        yield
    finally:
        _model_override.reset(token)
        _billed_user.reset(billed)

class MultiKeyChain(Runnable):
    def __init__(self, llms: List[Any]):
        self.llms = llms
        # Basic validation
        if not self.llms:
            raise ValueError("MultiKeyChain cannot be initialized with empty LLM list")

    def bind_tools(self, tools: Any, **kwargs) -> "MultiKeyChain":
        """Bind tools to all underlying LLMs"""
        bound_llms = [llm.bind_tools(tools, **kwargs) for llm in self.llms]
        return MultiKeyChain(bound_llms)

    async def ainvoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs) -> Any:
        errors = []
        for i, llm in enumerate(self.llms):
            try:
                if i > 0:
                    logger.info(f"Fallback: Switching to API Key #{i+1}")
                return await llm.ainvoke(input, config, **kwargs)
            except Exception as e:
                logger.warning(f"Error with API Key #{i+1}: {e}")
                errors.append(e)
        
        raise Exception(f"All API keys failed. Last error: {errors[-1]}")



    async def astream_events(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs) -> AsyncIterator[Any]:
        errors = []
        for i, llm in enumerate(self.llms):
            try:
                if i > 0:
                    logger.info(f"Fallback: Switching to API Key #{i+1}")
                async for event in llm.astream_events(input, config, **kwargs):
                    yield event
                return
            except Exception as e:
                logger.warning(f"Error with API Key #{i+1}: {e}")
                errors.append(e)
        
        raise Exception(f"All API keys failed. Last error: {errors[-1]}")
    
    def invoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs) -> Any:
        errors = []
        for i, llm in enumerate(self.llms):
            try:
                if i > 0:
                    logger.info(f"Fallback: Switching to API Key #{i+1}")
                return llm.invoke(input, config, **kwargs)
            except Exception as e:
                logger.warning(f"Error with API Key #{i+1}: {e}")
                errors.append(e)
        raise Exception(f"All API keys failed. Last error: {errors[-1]}")



class LLMService:


    def __init__(self):
        # We prefer using LangChain for agents, but this client is for direct single usage if needed
        self.keys = settings.OMNIROUTE_API_KEYS
        self.feature_keys = settings.OMNIROUTE_FEATURE_KEYS
        if not self.keys:
            logger.warning("OMNIROUTE_API_KEY(S) not set. LLM features will be disabled.")

    def keys_for(self, feature: Optional[str]) -> List[str]:
        """The feature's own gateway key alone -- its OmniRoute daily budget is
        the feature's budget, so no spill-over -- else the shared key(s)."""
        own = self.feature_keys.get(feature) if feature else None
        return [own] if own else list(self.keys)

    async def get_completion(self, prompt: str, system_prompt: str, tier: Optional[str] = None,
                             feature: Optional[str] = None) -> str:
        """Both prompts come from backend/prompts/*.md via prompts.render.
        `tier` (fast / standard / deep) picks the admin's model for that
        kind of task; see app_settings.TIERS. `feature` picks the gateway key
        its usage is metered under."""
        llm = await self.get_llm(tier=tier, feature=feature)
        if not llm:
            return "LLM_DISABLED"
        
        try:
            # MultiKeyChain or ChatGoogleGenerativeAI supports ainvoke
            from langchain_core.messages import HumanMessage, SystemMessage
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt)
            ]
            
            response = await llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            return f"Error generating response: {str(e)}"

    async def _charge(self, feature: Optional[str]) -> None:
        """Counts a call made inside a user's request (use_model(user_id=...))
        against their daily ceiling; raises DailyLimitReached past it. Fails
        open on a Redis problem, like every rate limit here."""
        user_id = _billed_user.get()
        if not user_id or feature not in USER_FEATURES:
            return
        from datetime import datetime, timezone

        from backend.database import db
        from backend.engine.session import IST
        from backend.rate_limit import allow

        day = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
        if not await allow(db.redis, f"llm:{user_id}:{day}", settings.USER_LLM_CALLS_PER_DAY, 2 * 86400):
            raise DailyLimitReached(user_id)

    async def get_llm(self, tier: Optional[str] = None, feature: Optional[str] = None):
        """Returns a MultiKeyChain wrapping ChatOpenAI instances pointed at the OmniRoute gateway"""
        from langchain_openai import ChatOpenAI

        if feature and not await feature_enabled(feature):
            return None  # switched off by an admin: callers take their "LLM disabled" path
        await self._charge(feature)

        keys = self.keys_for(feature)
        if not keys:
            return None

        model = _model_override.get() or await current_llm_model(tier=tier)
        llms = []
        for key in keys:
            llms.append(ChatOpenAI(
                model=model,
                api_key=key,
                base_url=settings.OMNIROUTE_BASE_URL,
                temperature=0.0,
                max_retries=0 # We handle retries via rotation
            ))
            
        if len(llms) == 1:
            return llms[0]
            
        return MultiKeyChain(llms)

llm_service = LLMService()
