from app.llm.errors import BudgetExceeded
from app.llm.types import LLMResult


class Budget:
    """Token / cost ceiling for one agent run. Shared by every call made in that run."""

    def __init__(self, max_tokens: int | None = None, max_cost_usd: float | None = None) -> None:
        self.max_tokens = max_tokens
        self.max_cost_usd = max_cost_usd
        self.tokens_used = 0
        self.cost_used = 0.0

    def check(self) -> None:
        """Called before a call: refuse to start if the budget is already spent."""
        if self._over(at_least=True):
            raise self._error()

    def charge(self, result: LLMResult) -> None:
        """Called after a call: record usage, raise if it pushed the run over the limit."""
        self.tokens_used += result.tokens_in + result.tokens_out
        self.cost_used += result.cost_usd_estimate
        if self._over(at_least=False):
            raise self._error()

    def _over(self, *, at_least: bool) -> bool:
        def hit(used: float, limit: float | None) -> bool:
            if limit is None:
                return False
            return used >= limit if at_least else used > limit

        return hit(self.tokens_used, self.max_tokens) or hit(self.cost_used, self.max_cost_usd)

    def _error(self) -> BudgetExceeded:
        return BudgetExceeded(
            f"LLM budget exceeded: {self.tokens_used}/{self.max_tokens} tokens, "
            f"${self.cost_used:.6f}/{self.max_cost_usd} cost",
            tokens_used=self.tokens_used,
            cost_used=self.cost_used,
        )
