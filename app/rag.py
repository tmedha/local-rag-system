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
    "warranted, citing the exact supporting text.\n"
    "- If the user sends a short acknowledgment or closing remark (e.g. \"ok\", \"thanks\", "
    "\"fine\", \"got it\", \"cool\"), reply briefly and politely (e.g. \"Glad that helps!\"). "
    "Do NOT repeat your previous answer, do NOT mention documents or your knowledge base, "
    "and do NOT say \"I don't have that in the documents.\""
)

# Short social turns that should not trigger retrieval or a re-answer.
_ACKNOWLEDGMENTS = {
    "ok", "okay", "k", "kk", "thanks", "thank you", "ty", "thx", "fine", "cool",
    "great", "got it", "nice", "sure", "alright", "all right", "good", "perfect",
    "awesome", "yep", "yes", "no", "np", "understood",
}


def is_acknowledgment(text: str) -> bool:
    """True for short social/closing turns that aren't real questions."""
    cleaned = text.strip().lower().rstrip(".!").strip()
    return cleaned in _ACKNOWLEDGMENTS


REFUSAL = "I don't have that in the documents."


def is_refusal(answer: str) -> bool:
    """True when the model declined for lack of grounding (so we hide sources)."""
    return answer.strip().lower().startswith("i don't have that in the documents")


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


def _gate(results: list[dict]) -> list[dict]:
    """Keep passages that clear the absolute floor AND are within ``relevance_margin``
    of *this source's* best hit. Gating each source independently is important: a strong
    vault match must not raise the bar for the session's uploads (or vice-versa)."""
    if not results:
        return []
    best = max(1.0 - r["distance"] for r in results)
    threshold = max(settings.min_score, best - settings.relevance_margin)
    kept = [r for r in results if (1.0 - r["distance"]) >= threshold]
    kept.sort(key=lambda r: r["distance"])
    return kept


def retrieve(question: str, session_id: str | None) -> list[dict]:
    """Retrieve top-k relevant passages across the vault and the session's uploads.

    Vault and uploads are gated separately (see ``_gate``) so a large/high-scoring vault
    can't crowd out a file the user just uploaded for this chat. The best upload hit is
    always kept if it clears the floor, guaranteeing uploaded files are actually consulted.

    Short acknowledgments ("ok", "thanks") retrieve nothing: they're social turns, not
    questions, so injecting document context only makes the model ramble.
    """
    if is_acknowledgment(question):
        return []

    query_embedding = embed_query(_retrieval_query(question, session_id))
    vault = _gate(_query_collection(get_vault_collection(), query_embedding, None))
    uploads = []
    if session_id:
        uploads = _gate(
            _query_collection(
                get_uploads_collection(), query_embedding, {"session_id": session_id}
            )
        )
    if not vault and not uploads:
        return []

    merged = sorted(vault + uploads, key=lambda r: r["distance"])
    final = merged[: settings.top_k]
    # Guarantee the best relevant upload is represented, even if vault chunks fill top-k.
    if uploads and not any(r["metadata"].get("origin") == "upload" for r in final):
        final = final[: settings.top_k - 1] + [uploads[0]]
        final.sort(key=lambda r: r["distance"])
    return final


def build_messages(
    question: str, passages: list[dict], session_id: str | None
) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if session_id:
        for m in history.recent_messages(session_id, settings.history_turns):
            messages.append({"role": m["role"], "content": m["content"]})

    if is_acknowledgment(question):
        # Social turn: send it plainly so the model gives a brief, natural reply
        # instead of commenting on a "(no matching documents)" scaffold.
        user_content = question
    else:
        blocks = []
        for i, p in enumerate(passages, 1):
            meta = p["metadata"]
            label = meta.get("source", "unknown")
            if meta.get("locator"):
                label += f" ({meta['locator']})"
            blocks.append(f"[{i}] {label}:\n{p['text']}")
        context = "\n\n".join(blocks) if blocks else "(no matching documents)"
        user_content = f"Context from the documents:\n\n{context}\n\nQuestion: {question}"

    messages.append({"role": "user", "content": user_content})
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
    # A refusal isn't grounded in anything, so don't attach misleading sources.
    if is_refusal(text):
        passages = []
    return {
        "answer": text,
        "sources": sources_of(passages),
        "passages": passages_payload(passages),
    }
