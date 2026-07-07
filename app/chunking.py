"""Split text into overlapping chunks for embedding."""
from __future__ import annotations

from .loaders import Segment


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Sliding-window chunking that prefers to break on whitespace."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    n = len(text)
    start = 0
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # Try to end on a space so we don't cut words in half.
            space = text.rfind(" ", start + overlap, end)
            if space > start:
                end = space
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_segments(
    segments: list[Segment], chunk_size: int, overlap: int
) -> list[Segment]:
    """Chunk each ``(text, locator)`` segment, preserving its locator on every chunk."""
    out: list[Segment] = []
    for text, locator in segments:
        for chunk in chunk_text(text, chunk_size, overlap):
            out.append((chunk, locator))
    return out
