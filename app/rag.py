"""Retrieval-augmented generation: retrieve, build a grounded prompt, generate."""
from __future__ import annotations

from . import history, llm
from .config import settings
from .embeddings import embed_query
from .vectorstore import get_uploads_collection, get_vault_collection

SYSTEM_PROMPT = (
    "You are CloakedOracle, a privacy-first assistant that answers from the user's local "
    "documents.\n\n"
    "Grounding rules:\n"
    "- Read the provided context carefully and base every factual claim ONLY on it. Do "
    "not use outside knowledge or invent details.\n"
    "- Quote exact figures, names, and dates from the context rather than paraphrasing "
    "loosely.\n"
    "- When you state a fact, mention which source file it came from.\n"
    "- If the user asks a NEW factual question that the context does not cover, reply "
    'exactly: "I don\'t have that in the documents."\n\n'
    "Conversation rules:\n"
    "- If the user is reacting to or asking about the ongoing conversation (e.g. saying "
    "your answer is wrong, asking if you are sure, or asking you to clarify, re-check, or "
    "explain more simply), DO engage: re-examine the context and prior turns and respond "
    "helpfully. Do not fall back to \"I don't have that in the documents\" for these "
    "conversational turns.\n"
    "- If the user points out you were wrong, re-read the context and correct yourself if "
    "warranted, citing the exact supporting text."
)


def _query_collection(collection, query_embedding, where) -> list[dict]:
    count = collection.count()
    if count == 0:
        return []
    res = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(settings.top_k, count),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]
    return [
        {"text": doc, "metadata": meta, "distance": dist}
        for doc, meta, dist in zip(docs, metas, dists)
    ]


def _retrieval_query(question: str, session_id: str | None) -> str:
    """Expand short follow-ups with the previous question so they still retrieve.

    A meta turn like "it's wrong" or "are you sure?" carries no searchable content on
    its own. Prepending the prior user question lets retrieval re-pull the documents the
    conversation is actually about, instead of matching nothing.
    """
    if not session_id:
        return question
    prev = history.last_user_message(session_id)
    return f"{prev}\n{question}" if prev else question


def retrieve(question: str, session_id: str | None) -> list[dict]:
    """Retrieve top-k *relevant* passages across the vault and session uploads.

    Chroma always returns its nearest neighbors even when nothing in the store is
    actually related to the question (e.g. a two-document vault where only one is on
    topic). We drop anything below ``min_score`` so the evidence panel — and the
    context handed to the LLM — only ever contains passages that genuinely bear on
    the question, not just "closest of what's available".
    """
    query_embedding = embed_query(_retrieval_query(question, session_id))
    results = _query_collection(get_vault_collection(), query_embedding, None)
    if session_id:
        results += _query_collection(
            get_uploads_collection(), query_embedding, {"session_id": session_id}
        )
    results = [r for r in results if (1.0 - r["distance"]) >= settings.min_score]
    results.sort(key=lambda r: r["distance"])
    return results[: settings.top_k]


def build_messages(
    question: str, passages: list[dict], session_id: str | None
) -> list[dict]:
    blocks = []
    for i, p in enumerate(passages, 1):
        meta = p["metadata"]
        label = meta.get("source", "unknown")
        if meta.get("locator"):
            label += f" ({meta['locator']})"
        blocks.append(f"[{i}] {label}:\n{p['text']}")
    context = "\n\n".join(blocks) if blocks else "(no matching documents)"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if session_id:
        for m in history.recent_messages(session_id, settings.history_turns):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append(
        {
            "role": "user",
            "content": f"Context from the documents:\n\n{context}\n\nQuestion: {question}",
        }
    )
    return messages


def sources_of(passages: list[dict]) -> list[dict]:
    """Distinct source files (name + origin), preserving retrieval order."""
    seen = set()
    sources = []
    for p in passages:
        meta = p["metadata"]
        key = (meta.get("source"), meta.get("origin"))
        if key not in seen:
            seen.add(key)
            sources.append({"name": meta.get("source"), "origin": meta.get("origin")})
    return sources


def passages_payload(passages: list[dict]) -> list[dict]:
    """Evidence-panel payload: passage text + provenance + similarity score."""
    return [
        {
            "text": p["text"],
            "source": p["metadata"].get("source"),
            "origin": p["metadata"].get("origin"),
            "locator": p["metadata"].get("locator") or "",
            "score": round(1.0 - p["distance"], 4),
        }
        for p in passages
    ]


def answer(question: str, session_id: str) -> dict:
    """Non-streaming: retrieve, generate, and return answer + sources + passages."""
    passages = retrieve(question, session_id)
    messages = build_messages(question, passages, session_id)
    text = llm.chat(messages)
    return {
        "answer": text,
        "sources": sources_of(passages),
        "passages": passages_payload(passages),
    }
