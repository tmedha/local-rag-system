"""SQLite-backed chat history: sessions + messages.

Uses the built-in ``sqlite3`` module (no extra dependency). One file at
``storage/chats.db`` holds all sessions, enabling a session list, resume, per-session
delete, and count-based pruning.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from .config import settings


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at REAL,
                updated_at REAL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                content TEXT,
                sources TEXT,
                created_at REAL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session "
            "ON messages(session_id, created_at)"
        )


def create_session(title: str = "New chat") -> str:
    sid = uuid.uuid4().hex
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sid, title, now, now),
        )
    return sid


def session_exists(session_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return row is not None


def list_sessions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions "
            "ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_messages(session_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content, sources, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    messages = []
    for r in rows:
        m = dict(r)
        m["sources"] = json.loads(m["sources"]) if m["sources"] else []
        messages.append(m)
    return messages


def recent_messages(session_id: str, limit: int) -> list[dict]:
    """Most recent turns (oldest-first) for feeding back as in-session memory."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def last_user_message(session_id: str) -> str | None:
    """The most recent prior user turn — used to expand a follow-up for retrieval."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return row["content"] if row else None


def append_message(
    session_id: str, role: str, content: str, sources: list | None = None
) -> str:
    mid = uuid.uuid4().hex
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mid, session_id, role, content, json.dumps(sources or []), now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
        )
    return mid


def maybe_set_title(session_id: str, text: str) -> None:
    """Set a session's title from its first user message (if still the default)."""
    title = text.strip().splitlines()[0][:60] if text.strip() else "New chat"
    with _conn() as conn:
        conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ? AND title = 'New chat'",
            (title, session_id),
        )


def delete_session(session_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def prune(max_sessions: int) -> list[str]:
    """Keep the newest ``max_sessions`` sessions; delete older ones.

    Returns the deleted session ids so callers can purge their ephemeral uploads.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        stale = [r["id"] for r in rows[max_sessions:]]
        for sid in stale:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    return stale
