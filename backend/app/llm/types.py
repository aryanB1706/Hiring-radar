"""Provider-neutral types shared by every LLMClient implementation."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelTier(StrEnum):
    DEFAULT = "default"  # GEMINI_MODEL: reasoning, agent loop
    FAST = "fast"  # GEMINI_FAST_MODEL: cheap classification


class LLMResult(BaseModel):
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    cost_usd_estimate: float = 0.0
    cached: bool = False


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments

    @classmethod
    def from_model(cls, name: str, description: str, input_model: type[BaseModel]) -> "ToolSpec":
        return cls(name=name, description=description, parameters=input_model.model_json_schema())


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
    # Opaque provider state that must be replayed with the history (e.g. Gemini thought signature).
    provider_data: dict[str, Any] | None = None


class AssistantTurn(BaseModel):
    """What the model did: answered with text, asked for tools, or both."""

    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    result: LLMResult


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)  # role == "assistant"
    tool_call_id: str | None = None  # role == "tool"
    tool_name: str | None = None  # role == "tool"

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls(role="user", text=text)

    @classmethod
    def from_turn(cls, turn: AssistantTurn) -> "Message":
        return cls(role="assistant", text=turn.text, tool_calls=turn.tool_calls)

    @classmethod
    def tool_result(cls, call: ToolCall, text: str) -> "Message":
        return cls(role="tool", text=text, tool_call_id=call.id, tool_name=call.name)
