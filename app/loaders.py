"""Document loaders: parse supported file types into text segments.

Each loader returns a list of ``(text, locator)`` segments. The locator is a short,
human-readable pointer to where the text came from (e.g. ``"p.3"`` for a PDF page); it
may be an empty string when no meaningful locator exists. Segments are later chunked,
carrying their locator along for citation in the evidence panel.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}

Segment = tuple[str, str]  # (text, locator)


def load_path(path: Path) -> list[Segment]:
    """Load a file from disk into text segments."""
    return load_bytes(path.read_bytes(), path.name)


def load_bytes(data: bytes, filename: str) -> list[Segment]:
    """Load raw bytes into text segments, dispatching on the filename extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _load_pdf(data)
    if ext in {".txt", ".md"}:
        return [(data.decode("utf-8", errors="replace"), "")]
    if ext == ".docx":
        return _load_docx(data)
    raise ValueError(f"Unsupported file type: {ext or '(none)'}")


def _load_pdf(data: bytes) -> list[Segment]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    segments: list[Segment] = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append((text, f"p.{i + 1}"))
    return segments


def _load_docx(data: bytes) -> list[Segment]:
    import docx

    document = docx.Document(io.BytesIO(data))
    text = "\n".join(p.text for p in document.paragraphs if p.text.strip())
    return [(text, "")] if text.strip() else []
