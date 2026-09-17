"""GeminiClient against the REAL google-genai SDK with the HTTP layer mocked (no network)."""

import base64
import json
from collections.abc import Callable

import httpx
import pytest
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.llm import Message, ModelTier, ToolCall, ToolSpec
from app.llm.errors import LLMPermanentError, LLMRateLimitError, LLMTransientError
from app.llm.gemini import GeminiClient

Handler = Callable[[httpx.Request], httpx.Response]


class Job(BaseModel):
    title: str


def gemini_with(handler: Handler) -> GeminiClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sdk = genai.Client(api_key="test-key", http_options=types.HttpOptions(httpx_async_client=http))
    return GeminiClient(api_key="test-key", model="main-model", fast_model="fast-model", client=sdk)


def reply(parts: list[dict], usage: dict | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
            "usageMetadata": usage
            or {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 3},
        },
    )


def error_reply(code: int, status: str, details: list[dict] | None = None) -> httpx.Response:
    body = {"error": {"code": code, "message": "boom", "status": status, "details": details or []}}
    return httpx.Response(code, json=body)


async def test_generate_json_sends_schema_and_reads_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply([{"text": '{"title": "Dev"}'}])

    result = await gemini_with(handler).generate_json(
        "classify this", Job, system="be terse", purpose="t"
    )

    request = seen[0]
    body = json.loads(request.content)
    assert "main-model:generateContent" in request.url.path
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"]["properties"]["title"]
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert result.text == '{"title": "Dev"}'
    assert (result.tokens_in, result.tokens_out) == (10, 8)  # thinking tokens count as output
    assert result.model == "main-model"


async def test_fast_tier_uses_the_fast_model() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return reply([{"text": "hi"}])

    result = await gemini_with(handler).generate_text("p", purpose="t", tier=ModelTier.FAST)
    assert "fast-model:generateContent" in paths[0]
    assert result.model == "fast-model"


async def test_429_becomes_a_rate_limit_error_carrying_the_retry_delay() -> None:
    retry_info = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "34s"}
    llm = gemini_with(lambda r: error_reply(429, "RESOURCE_EXHAUSTED", [retry_info]))

    with pytest.raises(LLMRateLimitError) as info:
        await llm.generate_text("p", purpose="t")
    assert info.value.retry_after == 34.0


async def test_retry_after_header_is_used_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response = error_reply(429, "RESOURCE_EXHAUSTED")
        response.headers["Retry-After"] = "12"
        return response

    with pytest.raises(LLMRateLimitError) as info:
        await gemini_with(handler).generate_text("p", purpose="t")
    assert info.value.retry_after == 12.0


async def test_5xx_is_transient_and_other_4xx_is_permanent() -> None:
    with pytest.raises(LLMTransientError):
        await gemini_with(lambda r: error_reply(503, "UNAVAILABLE")).generate_text("p", purpose="t")
    with pytest.raises(LLMPermanentError):
        await gemini_with(lambda r: error_reply(400, "INVALID_ARGUMENT")).generate_text(
            "p", purpose="t"
        )


async def test_network_errors_are_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(LLMTransientError):
        await gemini_with(handler).generate_text("p", purpose="t")


SIGNATURE = base64.b64encode(b"sig-bytes").decode()


async def test_tool_call_round_trip_keeps_thought_signature_and_merges_results() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return reply(
                [
                    {"text": "Let me look.", "thought": True},
                    {
                        "functionCall": {"name": "search_company", "args": {"name": "Acme"}},
                        "thoughtSignature": SIGNATURE,
                    },
                    {"functionCall": {"name": "fetch_page", "args": {"url": "https://a.com"}}},
                ]
            )
        return reply([{"text": "Acme looks legit."}])

    llm = gemini_with(handler)
    tools = [
        ToolSpec(
            name="search_company", description="find a company", parameters={"type": "object"}
        ),
        ToolSpec(name="fetch_page", description="fetch", parameters={"type": "object"}),
    ]
    history = [Message.user("check Acme")]

    turn = await llm.generate_with_tools(history, tools, system="agent", purpose="t")

    assert turn.text is None  # thought parts are not surfaced as answer text
    assert [c.name for c in turn.tool_calls] == ["search_company", "fetch_page"]
    assert turn.tool_calls[0].arguments == {"name": "Acme"}
    assert turn.tool_calls[0].provider_data == {"thought_signature": SIGNATURE}
    first_body = requests[0]
    names = [d["name"] for d in first_body["tools"][0]["functionDeclarations"]]
    assert names == ["search_company", "fetch_page"]

    history += [
        Message.from_turn(turn),
        Message.tool_result(turn.tool_calls[0], json.dumps({"employees": 50})),
        Message.tool_result(turn.tool_calls[1], "plain text page"),
    ]
    final = await llm.generate_with_tools(history, tools, purpose="t")

    assert final.text == "Acme looks legit." and final.tool_calls == []
    contents = requests[1]["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]  # results share one turn
    model_parts = contents[1]["parts"]
    assert model_parts[0]["thoughtSignature"] == SIGNATURE  # replayed exactly
    results = contents[2]["parts"]
    assert results[0]["functionResponse"]["response"] == {"employees": 50}
    assert results[1]["functionResponse"]["response"] == {"result": "plain text page"}


def test_tool_spec_can_be_built_from_a_pydantic_model() -> None:
    class Args(BaseModel):
        url: str

    spec = ToolSpec.from_model("fetch_page", "Fetch a page", Args)
    assert spec.parameters["properties"]["url"]["type"] == "string"
    assert ToolCall(id="1", name="x", arguments={}).provider_data is None
