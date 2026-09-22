import hashlib
import math
import re

from app.embeddings.base import Embedder

_TOKEN = re.compile(r"[a-z0-9]+")


class FakeEmbedder(Embedder):
    """Deterministic stand-in for tests: a hashed bag of words, normalized. Texts that share
    most of their words get close vectors, so dedupe tests behave sensibly without a model."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _TOKEN.findall(text.lower()):
            index = int(hashlib.md5(token.encode()).hexdigest()[:8], 16) % self.dim
            vector[index] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
