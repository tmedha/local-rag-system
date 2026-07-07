"""Index the read-only vault folder into the persistent Chroma collection.

The folder is treated as authoritative and READ-ONLY: this module only reads files, never
creates/writes/deletes them. A manifest tracks file hashes so unchanged files are skipped,
changed files are re-indexed, and files removed from disk have their chunks purged.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from .chunking import chunk_segments
from .config import settings
from .embeddings import embed_texts
from .loaders import SUPPORTED_EXTENSIONS, load_path
from .vectorstore import get_vault_collection

logger = logging.getLogger(__name__)


def _load_manifest() -> dict:
    if settings.manifest_path.exists():
        return json.loads(settings.manifest_path.read_text())
    return {}


def _save_manifest(manifest: dict) -> None:
    settings.manifest_path.write_text(json.dumps(manifest, indent=2))


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index_file(collection, path: Path, rel: str) -> list[str]:
    try:
        segments = load_path(path)
    except Exception as exc:  # unreadable/corrupt file — skip, don't crash startup
        logger.warning("Skipping %s: %s", rel, exc)
        return []

    chunks = chunk_segments(segments, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        logger.info("No extractable text in %s", rel)
        return []

    texts = [text for text, _ in chunks]
    embeddings = embed_texts(texts)
    ids, metadatas = [], []
    name = Path(rel).name
    for i, (_, locator) in enumerate(chunks):
        ids.append(f"vault::{rel}::{i}")
        metadatas.append(
            {
                "origin": "vault",
                "source": name,
                "path": rel,
                "chunk_index": i,
                "locator": locator,
            }
        )
    collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
    return ids


def reindex() -> dict:
    """Sync the vault collection with the current contents of documents/."""
    collection = get_vault_collection()
    manifest = _load_manifest()
    seen: set[str] = set()
    added = updated = removed = 0

    for path in sorted(settings.documents_dir.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        rel = str(path.relative_to(settings.documents_dir))
        seen.add(rel)
        record = manifest.get(rel)
        file_hash = _file_hash(path)
        if record and record.get("hash") == file_hash:
            continue  # unchanged

        # New or modified: drop stale chunks (if any) then re-index.
        if record and record.get("chunk_ids"):
            collection.delete(ids=record["chunk_ids"])
            updated += 1
        else:
            added += 1
        chunk_ids = _index_file(collection, path, rel)
        stat = path.stat()
        manifest[rel] = {
            "hash": file_hash,
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "chunk_ids": chunk_ids,
        }

    # Purge files that vanished from the folder.
    for rel in list(manifest):
        if rel not in seen:
            record = manifest.pop(rel)
            if record.get("chunk_ids"):
                collection.delete(ids=record["chunk_ids"])
            removed += 1

    _save_manifest(manifest)
    result = {"added": added, "updated": updated, "removed": removed, "files": len(seen)}
    logger.info("Reindex complete: %s", result)
    return result


def list_documents() -> list[dict]:
    """List indexed vault files (read-only view)."""
    manifest = _load_manifest()
    docs = []
    for rel, rec in sorted(manifest.items()):
        docs.append(
            {
                "name": Path(rel).name,
                "path": rel,
                "chunks": len(rec.get("chunk_ids", [])),
                "size": rec.get("size"),
            }
        )
    return docs


def stats() -> dict:
    return {"documents": len(_load_manifest()), "chunks": get_vault_collection().count()}
