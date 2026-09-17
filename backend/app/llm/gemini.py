import base64
import json
import time
from collections.abc import Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.llm.base import LLMClient
from app.llm.budget import Budget
from app.llm.errors import (
    LLMPermanentError,
    LLMRateLimitError,
    LLMTransientError,
)
from app.llm.types import AssistantTurn, LLMResult, Message, ModelTier, ToolCall, ToolSpec


def _retry_after(exc: errors.APIError) -> float | None:
    """Seconds the provider asked us to wait: Retry-After header or the RetryInfo error detail."""
    headers = getattr(exc.response, "headers", None)
    if headers is not None and (value := headers.get("retry-after")) is not None:
        try:
            return float(value)
        except ValueError:
            pass
    body = exc.details if isinstance(exc.details, dict) else {}
    for detail in body.get("error", {}).get("details", []):
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            delay = str(detail.get("retryDelay", "")).removesuffix("s")
            try:
                return float(delay)
            except ValueError:
                return None
    return None


def _translate(exc: Exception) -> Exception:
    """Map SDK / network errors onto the gateway's error types (retryable vs not)."""
    if isinstance(exc, errors.ClientError):
        if exc.code == 429:
            return LLMRateLimitError(str(exc), retry_after=_retry_after(exc))
        if exc.code == 408:
            return LLMTransientError(str(exc))
        return LLMPermanentError(str(exc))
    if isinstance(exc, errors.ServerError):
        return LLMTransientError(str(exc), retry_after=_retry_after(exc))
    if isinstance(exc, httpx.TransportError | TimeoutError):
        return LLMTransientError(f"network error: {exc!r}")
    return exc


class GeminiClient(LLMClient):
    """Single-attempt Gemini client (google-genai `generate_content`). Reliability is added by
    ReliableLLMClient, not here."""

    provider = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        fast_model: str,
        client: genai.Client | None = None,
    ) -> None:
        self._client = client or genai.Client(api_key=api_key)
        self._models = {ModelTier.DEFAULT: model, ModelTier.FAST: fast_model}

    def model_for(self, tier: ModelTier) -> str:
        return self._models[tier]

    async def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> LLMResult:
        config = types.GenerateContentConfig(system_instruction=system)
        response, latency_ms = await self._call(tier, prompt, config)
        return self._result(response, tier, latency_ms, text=response.text or "")

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
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
        )
        response, latency_ms = await self._call(tier, prompt, config)
        return self._result(response, tier, latency_ms, text=response.text or "")

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
        declarations = [
            types.FunctionDeclaration(
                name=t.name, description=t.description, parameters_json_schema=t.parameters
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)],
            # We run the tool loop ourselves; the SDK must not execute anything.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response, latency_ms = await self._call(tier, _to_contents(messages), config)

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        parts = (response.candidates[0].content.parts or []) if response.candidates else []
        for part in parts:
            if part.function_call is not None:
                calls.append(
                    ToolCall(
                        id=part.function_call.id or f"call_{len(calls)}",
                        name=part.function_call.name or "",
                        arguments=dict(part.function_call.args or {}),
                        provider_data=_encode_signature(part.thought_signature),
                    )
                )
            elif part.text and not part.thought:
                text_parts.append(part.text)
        text = "".join(text_parts) or None
        return AssistantTurn(
            text=text,
            tool_calls=calls,
            result=self._result(response, tier, latency_ms, text=text or ""),
        )

    async def _call(
        self,
        tier: ModelTier,
        contents: Any,
        config: types.GenerateContentConfig,
    ) -> tuple[types.GenerateContentResponse, int]:
        started = time.monotonic()
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model_for(tier), contents=contents, config=config
            )
        except Exception as exc:
            translated = _translate(exc)
            if translated is exc:
                raise
            raise translated from exc
        return response, int((time.monotonic() - started) * 1000)

    def _result(
        self,
        response: types.GenerateContentResponse,
        tier: ModelTier,
        latency_ms: int,
        *,
        text: str,
    ) -> LLMResult:
        usage = response.usage_metadata
        # Thinking tokens are billed as output tokens, so count them as such.
        tokens_out = (
            ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
            if usage
            else 0
        )
        return LLMResult(
            text=text,
            model=self.model_for(tier),
            tokens_in=(usage.prompt_token_count or 0) if usage else 0,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )


def _encode_signature(signature: bytes | None) -> dict[str, Any] | None:
    if not signature:
        return None
    return {"thought_signature": base64.b64encode(signature).decode()}


def _decode_signature(provider_data: dict[str, Any] | None) -> bytes | None:
    if not provider_data or "thought_signature" not in provider_data:
        return None
    return base64.b64decode(provider_data["thought_signature"])


def _tool_response(text: str | None) -> dict[str, Any]:
    """Gemini wants function results as an object; wrap anything that is not already one."""
    try:
        parsed = json.loads(text or "")
    except ValueError:
        return {"result": text or ""}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _to_contents(messages: Sequence[Message]) -> list[types.Content]:
    contents: list[types.Content] = []
    for msg in messages:
        if msg.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=msg.text or "")]))
        elif msg.role == "assistant":
            parts = [types.Part(text=msg.text)] if msg.text else []
            parts += [
                types.Part(
                    function_call=types.FunctionCall(id=c.id, name=c.name, args=c.arguments),
                    thought_signature=_decode_signature(c.provider_data),
                )
                for c in msg.tool_calls
            ]
            contents.append(types.Content(role="model", parts=parts))
        else:
            part = types.Part(
                function_response=types.FunctionResponse(
                    id=msg.tool_call_id, name=msg.tool_name, response=_tool_response(msg.text)
                )
            )
            previous = contents[-1] if contents else None
            if previous is not None and previous.role == "user" and _all_tool_results(previous):
                previous.parts = [*(previous.parts or []), part]  # parallel results share a turn
            else:
                contents.append(types.Content(role="user", parts=[part]))
    return contents


def _all_tool_results(content: types.Content) -> bool:
    return all(p.function_response is not None for p in content.parts or [])
