from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from app.llm.base import LLMClient
from app.llm.budget import Budget
from app.llm.types import AssistantTurn, LLMResult, Message, ModelTier, ToolCall, ToolSpec

Scripted = str | list[ToolCall] | Exception
"""One scripted reply: text (JSON text for generate_json), tool calls, or an exception to raise."""


class FakeLLMClient(LLMClient):
    """Scripted client for tests and CI: never touches the network.

    Give it a queue of replies (consumed in order) or a `responder(prompt) -> str` function.
    Every call is recorded in `.calls`.
    """

    provider = "fake"

    def __init__(
        self,
        responses: Sequence[Scripted] = (),
        *,
        responder: Callable[[str], str] | None = None,
        default_model: str = "fake-model",
        fast_model: str = "fake-fast-model",
    ) -> None:
        self._queue: deque[Scripted] = deque(responses)
        self._responder = responder
        self._models = {ModelTier.DEFAULT: default_model, ModelTier.FAST: fast_model}
        self.calls: list[dict[str, Any]] = []

    def model_for(self, tier: ModelTier) -> str:
        return self._models[tier]

    def _next(self, prompt: str) -> Scripted:
        if self._queue:
            return self._queue.popleft()
        if self._responder is not None:
            return self._responder(prompt)
        raise AssertionError("FakeLLMClient: no scripted response left")

    def _result(self, prompt: str, text: str, tier: ModelTier) -> LLMResult:
        return LLMResult(
            text=text,
            model=self.model_for(tier),
            tokens_in=max(1, len(prompt) // 4),
            tokens_out=max(1, len(text) // 4),
        )

    async def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> LLMResult:
        self.calls.append({"kind": "text", "prompt": prompt, "system": system, "purpose": purpose})
        reply = self._next(prompt)
        if isinstance(reply, Exception):
            raise reply
        assert isinstance(reply, str), "generate_text needs a text reply"
        return self._result(prompt, reply, tier)

    async def generate_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> LLMResult:
        self.calls.append(
            {
                "kind": "json",
                "prompt": prompt,
                "system": system,
                "purpose": purpose,
                "schema": schema.__name__,
            }
        )
        reply = self._next(prompt)
        if isinstance(reply, Exception):
            raise reply
        assert isinstance(reply, str), "generate_json needs a text reply"
        return self._result(prompt, reply, tier)

    async def generate_with_tools(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> AssistantTurn:
        last = messages[-1].text or "" if messages else ""
        self.calls.append(
            {
                "kind": "tools",
                "messages": list(messages),
                "tools": [t.name for t in tools],
                "system": system,
                "purpose": purpose,
            }
        )
        reply = self._next(last)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            return AssistantTurn(text=reply, result=self._result(last, reply, tier))
        return AssistantTurn(tool_calls=reply, result=self._result(last, "", tier))
