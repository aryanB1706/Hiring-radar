import pytest
from pydantic import BaseModel

from app.llm import FakeLLMClient, StructuredOutputError


class Job(BaseModel):
    title: str
    remote: bool


GOOD = '{"title": "Backend dev", "remote": true}'


async def test_valid_output_is_parsed_on_first_try() -> None:
    llm = FakeLLMClient([GOOD])
    job, result = await llm.generate_structured("classify", Job, purpose="test")
    assert job == Job(title="Backend dev", remote=True)
    assert len(llm.calls) == 1
    assert result.tokens_in > 0


async def test_invalid_json_is_retried_with_the_error_appended() -> None:
    llm = FakeLLMClient(["not json at all", GOOD])
    job, result = await llm.generate_structured("classify", Job, purpose="test")

    assert job.title == "Backend dev"
    assert len(llm.calls) == 2
    retry_prompt = llm.calls[1]["prompt"]
    assert retry_prompt.startswith("classify")
    assert "invalid" in retry_prompt
    # Usage is summed over both attempts.
    assert result.tokens_in == sum(max(1, len(c["prompt"]) // 4) for c in llm.calls)


async def test_schema_mismatch_is_retried_and_names_the_bad_field() -> None:
    llm = FakeLLMClient(['{"title": "x"}', GOOD])
    await llm.generate_structured("classify", Job, purpose="test")
    assert "remote" in llm.calls[1]["prompt"]


async def test_gives_up_after_max_retries() -> None:
    llm = FakeLLMClient(["nope"] * 5)
    with pytest.raises(StructuredOutputError) as info:
        await llm.generate_structured("classify", Job, purpose="test", max_retries=2)
    assert info.value.attempts == 3
    assert len(llm.calls) == 3


async def test_markdown_code_fence_is_tolerated() -> None:
    llm = FakeLLMClient([f"```json\n{GOOD}\n```"])
    job, _ = await llm.generate_structured("classify", Job, purpose="test")
    assert job.remote is True
    assert len(llm.calls) == 1
