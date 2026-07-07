"""CloakedOracle FastAPI application."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import history, ingest, llm, rag, uploads
from .config import BASE_DIR, settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cloakedoracle")

WEB_DIR = BASE_DIR / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    history.init_db()
    for sid in history.prune(settings.max_sessions):
        uploads.purge_session(sid)
    logger.info("Indexing vault folder: %s", settings.documents_dir)
    ingest.reindex()
    yield


app = FastAPI(title="CloakedOracle", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- models
class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None


def _require_session(session_id: str) -> None:
    if not history.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Unknown session")


# --------------------------------------------------------------------------- health / vault
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_model": settings.llm_model,
        "embed_model": settings.embed_model,
        **ingest.stats(),
    }


@app.get("/api/documents")
def documents():
    # The vault is read-only from the web layer: no create/delete routes exist.
    return {"documents": ingest.list_documents(), "read_only": True}


@app.post("/api/reindex")
def reindex():
    return ingest.reindex()


# --------------------------------------------------------------------------- sessions
@app.get("/api/sessions")
def sessions():
    return {"sessions": history.list_sessions()}


@app.post("/api/sessions")
def new_session():
    sid = history.create_session()
    for stale in history.prune(settings.max_sessions):
        uploads.purge_session(stale)
    return {"session_id": sid}


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    _require_session(session_id)
    return {
        "id": session_id,
        "messages": history.get_messages(session_id),
        "uploads": uploads.list_uploads(session_id),
    }


@app.delete("/api/sessions/{session_id}")
def session_delete(session_id: str):
    history.delete_session(session_id)
    uploads.purge_session(session_id)
    return {"deleted": session_id}


# --------------------------------------------------------------------------- session uploads
@app.post("/api/sessions/{session_id}/uploads")
async def upload_files(session_id: str, files: list[UploadFile] = File(...)):
    _require_session(session_id)
    results = []
    for f in files:
        data = await f.read()
        try:
            results.append(uploads.add_upload(session_id, data, f.filename))
        except Exception as exc:
            results.append({"name": f.filename, "error": str(exc)})
    return {"uploads": results, "files": uploads.list_uploads(session_id)}


@app.get("/api/sessions/{session_id}/uploads")
def list_uploads(session_id: str):
    _require_session(session_id)
    return {"files": uploads.list_uploads(session_id)}


@app.delete("/api/sessions/{session_id}/uploads/{name}")
def delete_upload(session_id: str, name: str):
    _require_session(session_id)
    uploads.delete_upload(session_id, name)
    return {"deleted": name, "files": uploads.list_uploads(session_id)}


# --------------------------------------------------------------------------- query
@app.post("/api/query")
def query(req: QueryRequest):
    sid = req.session_id
    if sid:
        _require_session(sid)
    else:
        sid = history.create_session()

    try:
        result = rag.answer(req.question, sid)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    history.append_message(sid, "user", req.question)
    history.append_message(sid, "assistant", result["answer"], result["sources"])
    history.maybe_set_title(sid, req.question)
    return {**result, "session_id": sid}


@app.get("/api/chat/stream")
def chat_stream(question: str, session_id: str | None = None):
    sid = session_id if session_id and history.session_exists(session_id) else history.create_session()

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    def generate():
        yield _sse({"type": "session", "session_id": sid})
        passages = rag.retrieve(question, sid)
        messages = rag.build_messages(question, passages, sid)
        collected: list[str] = []
        try:
            for token in llm.chat_stream(messages):
                collected.append(token)
                yield _sse({"type": "token", "token": token})
        except llm.LLMError as exc:
            yield _sse({"type": "error", "message": str(exc)})
            return

        text = "".join(collected)
        # A refusal isn't grounded in anything, so don't attach misleading sources.
        shown = [] if rag.is_refusal(text) else passages
        sources = rag.sources_of(shown)
        history.append_message(sid, "user", question)
        history.append_message(sid, "assistant", text, sources)
        history.maybe_set_title(sid, question)
        yield _sse(
            {
                "type": "done",
                "sources": sources,
                "passages": rag.passages_payload(shown),
            }
        )

    return StreamingResponse(generate(), media_type="text/event-stream")


# --------------------------------------------------------------------------- static UI
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
