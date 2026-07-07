"""Ephemeral per-session uploads.

Files uploaded through the UI are parsed from bytes in memory and indexed into the
in-memory Chroma client. They are NEVER written into the vault folder on disk, and they
disappear when the session is deleted or the server restarts.
"""
from __future__ import annotations

from pathlib import Path

from .chunking import chunk_segments
from .config import settings
from .embeddings import embed_texts
from .loaders import SUPPORTED_EXTENSIONS, load_bytes
from .vectorstore import get_uploads_collection

# session_id -> set of uploaded filenames (for listing in the UI)
_session_files: dict[str, set[str]] = {}


def _delete_file_chunks(session_id: str, filename: str) -> None:
    get_uploads_collection().delete(
        where={"$and": [{"session_id": session_id}, {"source": filename}]}
    )


def add_upload(session_id: str, data: bytes, filename: str) -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext or '(none)'}")

    segments = load_bytes(data, filename)
    chunks = chunk_segments(segments, settings.chunk_size, settings.chunk_overlap)

    # Replace any prior upload with the same name in this session.
    _delete_file_chunks(session_id, filename)

    if chunks:
        collection = get_uploads_collection()
        texts = [text for text, _ in chunks]
        embeddings = embed_texts(texts)
        ids, metadatas = [], []
        for i, (_, locator) in enumerate(chunks):
            ids.append(f"upload::{session_id}::{filename}::{i}")
            metadatas.append(
                {
                    "origin": "upload",
                    "session_id": session_id,
                    "source": filename,
                    "chunk_index": i,
                    "locator": locator,
                }
            )
        collection.add(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )

    _session_files.setdefault(session_id, set()).add(filename)
    return {"name": filename, "chunks": len(chunks)}


def list_uploads(session_id: str) -> list[str]:
    return sorted(_session_files.get(session_id, set()))


def delete_upload(session_id: str, filename: str) -> None:
    _delete_file_chunks(session_id, filename)
    files = _session_files.get(session_id)
    if files:
        files.discard(filename)


def purge_session(session_id: str) -> None:
    """Drop all of a session's uploaded chunks (on session delete / prune)."""
    if session_id in _session_files:
        get_uploads_collection().delete(where={"session_id": session_id})
        _session_files.pop(session_id, None)
