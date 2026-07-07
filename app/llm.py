"""Thin client for the local Ollama chat API."""
from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from .config import settings


class LLMError(RuntimeError):
    """Raised when the local Ollama server is unreachable or errors."""


def _url() -> str:
    return f"{settings.ollama_host}/api/chat"


def _options() -> dict:
    return {"temperature": settings.llm_temperature}


def chat(messages: list[dict]) -> str:
    """Non-streaming completion; returns the full assistant message text."""
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": False,
        "options": _options(),
    }
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(_url(), json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
    except httpx.HTTPError as exc:
        raise LLMError(_hint(exc)) from exc


def chat_stream(messages: list[dict]) -> Iterator[str]:
    """Yield assistant tokens as they arrive from Ollama."""
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": True,
        "options": _options(),
    }
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", _url(), json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
    except httpx.HTTPError as exc:
        raise LLMError(_hint(exc)) from exc


def _hint(exc: Exception) -> str:
    return (
        f"Could not reach Ollama at {settings.ollama_host} ({exc}). "
        f"Is `ollama serve` running and `{settings.llm_model}` pulled?"
    )
