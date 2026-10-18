"""A fake Telegram Bot API under aiogram's session: each call is recorded as
(token, method, params), params being the form fields aiogram puts on the
wire -- scalars as strings, objects and arrays decoded. The same tests passed
against the httpx transport this replaced. Nothing here touches a network.

    wire = TelegramWire(monkeypatch).on("sendMessage", {"message_id": 7, ...})
"""

import json
from dataclasses import dataclass

from aiogram.client.session.aiohttp import AiohttpSession


@dataclass
class Refused:
    """What a callable answer returns for a Bot API error."""
    status: int
    description: str


@dataclass
class Call:
    token: str
    method: str
    params: dict


def _field(value: str):
    return json.loads(value) if value[:1] in "[{" else value


def _message(message_id=100, chat_id=42, text="x"):
    return {"message_id": message_id, "date": 1_790_000_000, "chat": {"id": chat_id, "type": "private"}, "text": text}


class TelegramWire:
    def __init__(self, monkeypatch):
        self.calls: list[Call] = []
        self.answers: dict = {}
        wire = self

        async def aiogram_make_request(session, bot, method, timeout=None):
            params = {}
            for key, value in method.model_dump(warnings=False).items():
                value = session.prepare_value(value, bot=bot, files={})
                if value:
                    params[key] = _field(value)
            status, body = wire._answer(Call(bot.token, method.__api_method__, params))
            return session.check_response(bot=bot, method=method, status_code=status, content=json.dumps(body)).result

        monkeypatch.setattr(AiohttpSession, "make_request", aiogram_make_request)

    def on(self, method: str, result=True, status: int = 200, description: str = "") -> "TelegramWire":
        """Answer `method` with `result`, or with a Bot API error when status >= 400.
        `result` may be a callable(call) -> result."""
        self.answers[method] = (status, result, description)
        return self

    def _answer(self, call: Call):
        self.calls.append(call)
        status, result, description = self.answers.get(call.method, (200, None, ""))
        if call.method == "sendMessage" and result is None:
            result = _message(chat_id=int(call.params["chat_id"]), text=call.params.get("text", ""))
        if callable(result):
            result = result(call)
        if isinstance(result, Refused):
            status, description = result.status, result.description
        if status >= 400:
            return status, {"ok": False, "error_code": status, "description": description or "Bad Request"}
        return status, {"ok": True, "result": True if result is None else result}

    def sent(self, method: str) -> list[dict]:
        return [c.params for c in self.calls if c.method == method]
