from abc import ABC, abstractmethod


class Embedder(ABC):
    """Turns text into fixed-size vectors. Must match the schema: vector(384)."""

    dim: int = 384

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One unit-length vector per input text, in the same order."""
