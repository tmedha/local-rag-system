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
    """Embed passages/documents; vectors are L2-normalized for cosine similarity.

    No instruction prefix is applied here — bge-style models want the prefix on queries
    only, and passages are embedded plain (both in vault ingest and session uploads).
    """
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a search query, prepending the model's query instruction prefix if configured.

    bge models retrieve markedly better when the query carries the instruction prefix; the
    passage side stays plain (see ``embed_texts``). For models that don't use a prefix,
    leave ``query_prefix`` blank and this is a no-op.
    """
    prefix = settings.query_prefix.strip()
    query = f"{prefix} {text}" if prefix else text
    return embed_texts([query])[0]
