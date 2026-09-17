# 03 - LLM gateway

## Goal
`app/llm/` is the only place that talks to an LLM provider. Provider-agnostic interface, Gemini implementation, a fake for tests, and a reliability wrapper (retry, rate limit, cache, budget, logging).

## Scope
- `LLMClient` ABC: `generate_text`, `generate_structured` (Pydantic-validated, bounded retry with the validation error appended), `generate_with_tools` (provider-neutral `ToolSpec`/`ToolCall`/`AssistantTurn`/`Message`). Provider primitive for JSON mode: `generate_json`.
- Optional kwargs added to every method: `tier` (default model vs `GEMINI_FAST_MODEL`) and `budget`.
- `GeminiClient` (google-genai, `generate_content`, single attempt, typed errors), `FakeLLMClient` (scripted queue or function).
- `ReliableLLMClient(inner)` decorator, written once: exponential backoff + jitter on 429/5xx/timeouts (honors Retry-After, bounded, never retries other 4xx); Redis sliding-window rate limiter shared across workers; Redis response cache (key = hash of kind, model, system, prompt, schema); per-run `Budget` raising `BudgetExceeded`; structlog event + `llm_call_log` row per call; cost from a pricing table in settings.
- Settings: `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FAST_MODEL`, `LLM_RPM_LIMIT`, `LLM_CACHE_TTL_SECONDS`, `LLM_MAX_RETRIES`, plus `LLM_TIMEOUT_SECONDS`, `LLM_PRICING`.
- `build_llm_client(...)` factory so business code never constructs a provider.

## Out of scope
Classifier, agent loop, product prompts, Interactions API, streaming.

## Decisions
- Gemini via `models.generate_content` (the docs recommend the newer Interactions API for new projects; `generate_content` is still supported and has everything needed; swapping is a one-file change).
- Cache, rate limiter and DB logging fail open (warn, continue) so a Redis/DB blip never blocks a call. Tool-calling turns are not cached.
- Cached responses report `cached=True`, zero tokens and zero cost and do not consume budget or rate limit.
- The free-tier RPM isn't published outside AI Studio, so `LLM_RPM_LIMIT` defaults to a conservative placeholder.

## Acceptance checks
1. Bad JSON triggers a bounded retry with the error appended; success after a retry returns the parsed model; exhaustion raises `StructuredOutputError`.
2. 429 retries use backoff/Retry-After via a fake clock (no real sleeping); 4xx is not retried.
3. Cache hit skips the provider and is logged `cached=true`, cost 0; miss calls it.
4. `BudgetExceeded` raised when tokens/cost exceed the limit.
5. Rate limiter makes the (limit+1)th call wait.
6. Every call writes an `llm_call_log` row.
7. Live smoke test (`pytest -m live`) skipped without `GEMINI_API_KEY`.
