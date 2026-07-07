"""Local text embeddings via sentence-transformers (lazy singleton)."""
from __future__ import annotations

from functools import lru_cache

from .config import settings


@lru_cache(maxsize=1)
def _get_model():
    # Imported lazily so importing this module (e.g. for tests) is cheap.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embed_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts; vectors are L2-normalized for cosine similarity."""
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
