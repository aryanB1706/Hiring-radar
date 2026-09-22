import math

import pytest

from app.embeddings import FakeEmbedder, LocalEmbedder


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_fake_embedder_is_deterministic_unit_length_and_384_dims() -> None:
    first, again = await FakeEmbedder().embed(
        ["python backend developer", "python backend developer"]
    )
    assert len(first) == 384
    assert first == again
    assert math.isclose(cosine(first, first), 1.0)


async def test_fake_embedder_puts_similar_texts_closer() -> None:
    near_a, near_b, far = await FakeEmbedder().embed(
        [
            "senior python developer pune",
            "senior python developer pune remote",
            "graphic designer paris",
        ]
    )
    assert cosine(near_a, near_b) > cosine(near_a, far)


@pytest.mark.model
async def test_local_model_makes_384_dim_unit_vectors_with_sensible_similarity() -> None:
    embedder = LocalEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    job, similar, unrelated = await embedder.embed(
        [
            "Python backend developer, remote",
            "Backend engineer (Python, FastAPI), remote",
            "Pastry chef in Paris",
        ]
    )
    assert len(job) == 384
    assert math.isclose(cosine(job, job), 1.0, rel_tol=1e-4)
    assert cosine(job, similar) > cosine(job, unrelated)
