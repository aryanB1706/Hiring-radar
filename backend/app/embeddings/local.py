import asyncio
from typing import Any

from app.embeddings.base import Embedder


class LocalEmbedder(Embedder):
    """sentence-transformers on the CPU (all-MiniLM-L6-v2: 384 dims). The model loads lazily on
    first use, and encoding runs in a worker thread so it never blocks the event loop."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import, keep lazy

            model = SentenceTransformer(self._model_name)
            actual = model.get_embedding_dimension()
            if actual != self.dim:
                raise ValueError(
                    f"{self._model_name} makes {actual}-dim vectors, schema wants {self.dim}"
                )
            self._model = model
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [[float(x) for x in row] for row in vectors]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._encode, texts)
