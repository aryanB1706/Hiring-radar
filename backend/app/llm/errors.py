class LLMError(Exception):
    """Base class for everything the gateway raises."""


class LLMTransientError(LLMError):
    """Worth retrying: 429, 5xx, timeouts, network errors."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMRateLimitError(LLMTransientError):
    """The provider answered 429."""


class LLMPermanentError(LLMError):
    """Retrying cannot help: bad request, auth failure, blocked content."""


class LLMConfigError(LLMError):
    """The gateway is not configured (for example, no API key)."""


class BudgetExceeded(LLMError):
    def __init__(self, message: str, *, tokens_used: int, cost_used: float) -> None:
        super().__init__(message)
        self.tokens_used = tokens_used
        self.cost_used = cost_used


class StructuredOutputError(LLMError):
    def __init__(self, schema_name: str, attempts: int, last_error: str) -> None:
        super().__init__(f"{schema_name}: no valid output after {attempts} attempts: {last_error}")
        self.schema_name = schema_name
        self.attempts = attempts
        self.last_error = last_error
