from pydantic import BaseModel


class ModelPrice(BaseModel):
    input_per_mtok: float = 0.0  # USD per 1M input tokens
    output_per_mtok: float = 0.0  # USD per 1M output tokens


def estimate_cost(
    pricing: dict[str, ModelPrice], model: str, tokens_in: int, tokens_out: int
) -> float:
    """Unknown models cost 0 (free tier). The table lives in settings (LLM_PRICING)."""
    price = pricing.get(model)
    if price is None:
        return 0.0
    return (tokens_in * price.input_per_mtok + tokens_out * price.output_per_mtok) / 1_000_000
