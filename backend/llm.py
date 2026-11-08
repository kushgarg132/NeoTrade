
from backend.app_settings import current_llm_model, feature_enabled
from backend.configs.settings import settings
from backend.llm_tasks import TASKS
from typing import Optional, List, Any, AsyncIterator
import contextlib
import json
import time
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
# Every feature that names itself in get_llm; anything else counts as "other" (system status, per day).
COUNTED_FEATURES = ("chat", "research", "news", "plan", "portfolio", "learning", "other")


def calls_key(feature: Optional[str], day: str) -> str:
    return f"llm:calls:{feature if feature in COUNTED_FEATURES else 'other'}:{day}"


async def _count_call(feature: Optional[str]) -> None:
    """One more model call today for this feature (Redis, kept 2 days). Fails open.
    ponytail: counts get_llm hand-outs, so a tool loop on one handle counts once."""
    try:
        from datetime import datetime, timezone

        from backend.database import db
        from backend.engine.session import IST

        if db.redis is None:
            return
        key = calls_key(feature, datetime.now(timezone.utc).astimezone(IST).date().isoformat())
        await db.redis.incr(key)
        await db.redis.expire(key, 2 * 86400)
    except Exception as exc:
        logger.debug("llm call count skipped: %s", exc)


class DailyLimitReached(Exception):
    """The user has spent today's USER_LLM_CALLS_PER_DAY."""


LIMIT_MESSAGE = "You've used today's AI allowance. It resets at midnight IST."
DISABLED = "LLM_DISABLED"
_FAILED_PREFIX = "Error generating response"


def llm_failed(text: str) -> bool:
    """get_completion reports a switched-off feature or a failed call in its text."""
    return text == DISABLED or text.startswith(_FAILED_PREFIX)


def _ist_day() -> str:
    from datetime import datetime, timezone

    from backend.engine.session import IST

    return datetime.now(timezone.utc).astimezone(IST).date().isoformat()


def tokens_key(user_id: str, day: str) -> str:
    return f"llm:tokens:{user_id}:{day}"


def billed_user() -> Optional[str]:
    return _billed_user.get()


async def model_for(tier: Optional[str] = None) -> str:
    """The model a call made now would use: a use_model() override, else the tier's."""
    return _model_override.get() or await current_llm_model(tier=tier)


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

GOOGLE_PREFIX = "google/"


def route(model: str, gateway_keys: List[str]) -> tuple[str, str, List[str]]:
    """(model name, base URL, keys) for a model id: google/<name> goes straight
    to Google on GEMINI_API_KEY, anything else through OmniRoute."""
    if model.startswith(GOOGLE_PREFIX):
        keys = [settings.GEMINI_API_KEY] if settings.GEMINI_API_KEY else []
        return model.removeprefix(GOOGLE_PREFIX), settings.GEMINI_BASE_URL, keys
    return model, settings.OMNIROUTE_BASE_URL, gateway_keys


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
        started = False
        for i, llm in enumerate(self.llms):
            try:
                if i > 0:
                    logger.info(f"Fallback: Switching to API Key #{i+1}")
                async for event in llm.astream_events(input, config, **kwargs):
                    started = True
                    yield event
                return
            except Exception as e:
                if started:
                    raise  # a restart on another key would replay content the caller already has
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



# The last success and failure of get_completion, read by
# system/data_quality.py::_llm to tell "the provider is down" apart from one bad call.
LLM_OK_KEY, LLM_ERROR_KEY = "llm:last_ok", "llm:last_error"
# Set while Google refuses calls for lack of prepaid credit (gemini_chat.UsageRecorder).
GEMINI_CREDITS_KEY = "llm:gemini:depleted"


async def _note(key: str, value: str) -> None:
    from backend.database import db

    if db.redis is None:
        return
    try:
        await db.redis.set(key, value, ex=86400)
    except Exception as exc:
        logger.warning("could not record LLM health: %s", exc)


def _text(content: Any) -> str:
    if isinstance(content, list):  # some providers answer in content blocks
        return "".join(b if isinstance(b, str) else b.get("text", "") for b in content)
    return content


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

    async def get_completion(self, prompt: str, system_prompt: str, task: Optional[str] = None) -> str:
        """Both prompts come from backend/prompts/*.md via prompts.render.
        `task` names a row of llm_tasks.TASKS: model tier, budget, thinking, JSON."""
        llm = await self.get_llm(task=task)
        if not llm:
            return DISABLED
        
        try:
            # MultiKeyChain supports ainvoke
            from langchain_core.messages import HumanMessage, SystemMessage
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt)
            ]
            
            response = await llm.ainvoke(messages)
            content = _text(response.content)
            await _note(LLM_OK_KEY, str(int(time.time())))
            return content
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            await _note(LLM_ERROR_KEY, json.dumps({"at": int(time.time()), "error": str(e)[:300]}))
            return f"{_FAILED_PREFIX}: {str(e)}"

    async def stream_completion(self, prompt: str, system_prompt: str, task: Optional[str] = None) -> AsyncIterator[str]:
        """get_completion, but yields the text as the model writes it. One charge.
        A failure before the first chunk falls back to one plain call; after a
        chunk it raises, since the caller already holds part of the answer."""
        llm = await self.get_llm(task=task)
        if not llm:
            yield DISABLED
            return
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        started = False
        try:
            async for event in llm.astream_events(messages, version="v1"):
                if event["event"] != "on_chat_model_stream":
                    continue
                text = _text(event["data"]["chunk"].content)
                if text:
                    started = True
                    yield text
            await _note(LLM_OK_KEY, str(int(time.time())))
        except Exception as e:
            logger.error(f"LLM stream error: {e}")
            if started:
                await _note(LLM_ERROR_KEY, json.dumps({"at": int(time.time()), "error": str(e)[:300]}))
                raise
            try:
                text = _text((await llm.ainvoke(messages)).content)
            except Exception as e2:
                await _note(LLM_ERROR_KEY, json.dumps({"at": int(time.time()), "error": str(e2)[:300]}))
                raise
            await _note(LLM_OK_KEY, str(int(time.time())))
            yield text

    async def _charge(self, feature: Optional[str]) -> None:
        """Counts a call made inside a user's request (use_model(user_id=...))
        against their daily ceilings, raising DailyLimitReached past either: calls
        here, tokens as gemini_chat.UsageRecorder adds them up. Fails open on a
        Redis problem, like every rate limit here."""
        user_id = _billed_user.get()
        if not user_id or feature not in USER_FEATURES:
            return
        from backend.database import db
        from backend.rate_limit import allow

        day = _ist_day()
        try:
            used = int(await db.redis.get(tokens_key(user_id, day)) or 0)
        except Exception as exc:
            logger.warning("token allowance unreadable: %s", exc)
            used = 0
        if used >= settings.USER_LLM_TOKENS_PER_DAY:
            raise DailyLimitReached(user_id)
        if not await allow(db.redis, f"llm:{user_id}:{day}", settings.USER_LLM_CALLS_PER_DAY, 2 * 86400):
            raise DailyLimitReached(user_id)

    async def _over_budget(self, feature: Optional[str]) -> bool:
        """News has a daily spending ceiling; past it the batch waits, as for a switched-off feature."""
        if feature != "news":
            return False
        from backend.gemini_chat import spent_today

        return await spent_today(feature) >= settings.NEWS_USD_PER_DAY

    def _client(self, model: str, key: str, base_url: str, spec: Any, task: Optional[str], feature: Optional[str]):
        from langchain_openai import ChatOpenAI

        from backend.gemini_chat import GeminiChat, UsageRecorder

        google = model.startswith(GOOGLE_PREFIX)
        name = model.removeprefix(GOOGLE_PREFIX)
        options = {}
        if google and spec and spec.effort:
            options["reasoning_effort"] = spec.effort
        if google and spec and spec.json:
            options["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return (GeminiChat if google else ChatOpenAI)(
            model=name, api_key=key, base_url=base_url, temperature=0.0,
            max_retries=0,  # We handle retries via rotation
            callbacks=[UsageRecorder(name, task=task, feature=feature, gateway=not google)], **options)

    async def get_llm(self, tier: Optional[str] = None, feature: Optional[str] = None, task: Optional[str] = None):
        """Returns ChatOpenAI (a MultiKeyChain of them with several keys or a fallback) pointed at the model's provider"""
        spec = TASKS[task] if task else None
        if spec:
            tier, feature = spec.tier, spec.feature

        if feature and not await feature_enabled(feature):
            return None  # switched off by an admin: callers take their "LLM disabled" path
        if await self._over_budget(feature):
            return None
        await self._charge(feature)

        model = await model_for(tier)
        _, base_url, keys = route(model, self.keys_for(feature))
        llms = [self._client(model, key, base_url, spec, task, feature) for key in keys]
        if spec and spec.fallback and model.startswith(GOOGLE_PREFIX):
            backup = await current_llm_model()
            if not backup.startswith(GOOGLE_PREFIX):
                _, gateway_url, gateway_keys = route(backup, self.keys_for(feature))
                llms += [self._client(backup, key, gateway_url, spec, task, feature) for key in gateway_keys]
        if not llms:
            return None
        await _count_call(feature)
        return llms[0] if len(llms) == 1 else MultiKeyChain(llms)

llm_service = LLMService()
