from functools import lru_cache

from app.core.config import Settings
from app.embeddings.base import Embedder
from app.embeddings.local import LocalEmbedder


@lru_cache
def _local(model_name: str) -> LocalEmbedder:
    return LocalEmbedder(model_name)  # one per process: the model is slow to load


def get_embedder(settings: Settings) -> Embedder:
    return _local(settings.embedding_model)
