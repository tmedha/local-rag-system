"""Two Chroma stores: a persistent 'vault' collection and an ephemeral uploads client.

We compute embeddings ourselves (see ``embeddings.py``) and pass them explicitly, so no
Chroma-side embedding model is ever downloaded — keeping everything local and predictable.
"""
from __future__ import annotations

from .config import settings

_vault_client = None
_ephemeral_client = None

# Cosine space matches our L2-normalized embeddings.
_COSINE = {"hnsw:space": "cosine"}


def get_vault_collection():
    """Persistent, on-disk collection mirroring the read-only documents/ folder."""
    global _vault_client
    if _vault_client is None:
        import chromadb

        _vault_client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return _vault_client.get_or_create_collection("vault", metadata=_COSINE)


def get_uploads_collection():
    """In-memory collection for ephemeral per-session uploads (gone on restart)."""
    global _ephemeral_client
    if _ephemeral_client is None:
        import chromadb

        _ephemeral_client = chromadb.EphemeralClient()
    return _ephemeral_client.get_or_create_collection("uploads", metadata=_COSINE)
