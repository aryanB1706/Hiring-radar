import re
from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from app.llm.budget import Budget
from app.llm.errors import StructuredOutputError
from app.llm.types import AssistantTurn, LLMResult, Message, ModelTier, ToolSpec

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    match = _FENCE.match(text.strip())
    return match.group(1) if match else text


def _describe(exc: ValidationError) -> str:
    problems = []
    for err in exc.errors(include_input=False, include_url=False)[:5]:
        where = ".".join(str(p) for p in err["loc"]) or "output"
        problems.append(f"{where}: {err['msg']}")
    return "; ".join(problems)[:500]


class LLMClient(ABC):
    """The only interface business code uses to talk to a model."""

    provider: str = "unknown"

    @abstractmethod
    def model_for(self, tier: ModelTier) -> str: ...

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> LLMResult: ...

    @abstractmethod
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
        """Provider JSON mode: `result.text` is raw JSON, not yet validated."""

    @abstractmethod
    async def generate_with_tools(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        system: str | None = None,
        purpose: str,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> AssistantTurn: ...

    async def invalidate_cached_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None,
        tier: ModelTier,
    ) -> None:
        """Drop a cached reply that failed validation. Only caching clients override this."""
        return None

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        purpose: str,
        max_retries: int = 2,
        tier: ModelTier = ModelTier.DEFAULT,
        budget: Budget | None = None,
    ) -> tuple[T, LLMResult]:
        """Validated output. On bad JSON, retry (bounded) with the validation error appended.

        Written once here so every provider gets identical behaviour. The returned LLMResult
        sums usage over all attempts.
        """
        attempt_prompt = prompt
        total = LLMResult(text="", model=self.model_for(tier), cached=True)
        last_error = ""
        for _ in range(max_retries + 1):
            result = await self.generate_json(
                attempt_prompt, schema, system=system, purpose=purpose, tier=tier, budget=budget
            )
            total = total.model_copy(
                update={
                    "text": result.text,
                    "model": result.model,
                    "tokens_in": total.tokens_in + result.tokens_in,
                    "tokens_out": total.tokens_out + result.tokens_out,
                    "latency_ms": total.latency_ms + result.latency_ms,
                    "cost_usd_estimate": total.cost_usd_estimate + result.cost_usd_estimate,
                    "cached": total.cached and result.cached,
                }
            )
            try:
                return schema.model_validate_json(_strip_code_fence(result.text)), total
            except ValidationError as exc:
                last_error = _describe(exc)
                await self.invalidate_cached_json(attempt_prompt, schema, system=system, tier=tier)
                attempt_prompt = (
                    f"{prompt}\n\nYour previous reply was invalid ({last_error}). "
                    "Reply again with ONLY valid JSON that matches the schema."
                )
        raise StructuredOutputError(schema.__name__, max_retries + 1, last_error)
