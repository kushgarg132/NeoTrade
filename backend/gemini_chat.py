"""ChatOpenAI for Google's OpenAI-compatible endpoint.

Gemini 3 answers each tool call with a thought signature and rejects the next
request (400) unless the signature comes back on that call. langchain-openai
drops the field in both directions, so this class keeps it."""

from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr


class GeminiChat(ChatOpenAI):
    # ponytail: held per client, enough because get_llm makes one per agent run and
    # chat history is plain text. Persisted tool turns would need them stored with the messages.
    _signatures: dict = PrivateAttr(default_factory=dict)

    def _remember(self, raw: dict) -> None:
        for choice in raw.get("choices") or []:
            message = choice.get("message") or choice.get("delta") or {}
            for call in message.get("tool_calls") or []:
                signature = ((call.get("extra_content") or {}).get("google") or {}).get("thought_signature")
                if signature and call.get("id"):
                    self._signatures[call["id"]] = signature

    def _create_chat_result(self, response: Any, generation_info: Any = None):
        self._remember(response if isinstance(response, dict) else response.model_dump())
        return super()._create_chat_result(response, generation_info)

    def _convert_chunk_to_generation_chunk(self, chunk: dict, *args: Any, **kwargs: Any):
        self._remember(chunk)
        return super()._convert_chunk_to_generation_chunk(chunk, *args, **kwargs)

    def _get_request_payload(self, input_: Any, *, stop: Any = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload["messages"]:
            for call in message.get("tool_calls") or []:
                if signature := self._signatures.get(call["id"]):
                    call["extra_content"] = {"google": {"thought_signature": signature}}
        return payload
