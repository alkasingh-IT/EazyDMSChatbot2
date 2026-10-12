"""Persistent, user-scoped chat history storage.

The analytics databases are read-only by design, so chat history uses a small
dedicated SQLite store. Every read and write is scoped by the authenticated
U-UID supplied by the application gateway.
"""
from __future__ import annotations

import os
import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_ROOT = Path(__file__).resolve().parents[2]
_DB_PATH = Path(os.environ.get("CHAT_HISTORY_DB_PATH", str(_ROOT / ".dms_sessions" / "chat_history.sqlite3")))
_SHARD_COUNT = max(8, min(int(os.environ.get("CHAT_HISTORY_SHARDS", "64")), 256))
_SHARD_LOCKS = [threading.RLock() for _ in range(_SHARD_COUNT)]
_MAX_SESSIONS = 100
_MAX_MESSAGES = 200
_MAX_CONTENT = 12000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shard_index(u_uid: str) -> int:
    digest = hashlib.blake2b(u_uid.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % _SHARD_COUNT


def _shard_path(u_uid: str) -> Path:
    index = _shard_index(u_uid)
    suffix = _DB_PATH.suffix or ".sqlite3"
    stem = _DB_PATH.name[:-len(_DB_PATH.suffix)] if _DB_PATH.suffix else _DB_PATH.name
    return _DB_PATH.parent / f"{stem}-{index:03d}{suffix}"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        timeout=float(os.environ.get("CHAT_HISTORY_BUSY_TIMEOUT", "30")),
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        f"PRAGMA busy_timeout={int(float(os.environ.get('CHAT_HISTORY_BUSY_TIMEOUT', '30')) * 1000)}"
    )
    return conn


def init_chat_history() -> None:
    schema = """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                u_uid TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Chat',
                date_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_uid_updated
                ON chat_sessions (u_uid, updated_at DESC);
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                u_uid TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                data_snapshot TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chat_messages_uid_content
                ON chat_messages (u_uid, session_id, created_at);
        """
    for index in range(_SHARD_COUNT):
        path = _DB_PATH.parent / f"{_DB_PATH.stem}-{index:03d}{_DB_PATH.suffix or '.sqlite3'}"
        with _SHARD_LOCKS[index], _connect(path) as conn:
            conn.executescript(schema)
            try:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN data_snapshot TEXT")
            except Exception:
                pass


def _safe_uid(u_uid: str) -> str:
    value = str(u_uid or "").strip()
    if not value or len(value) > 256:
        raise ValueError("A valid U-UID is required")
    return value


def save_turn(u_uid: str, session_id: str, question: str, answer: str, data_snapshot: Optional[Dict[str, Any]] = None) -> str:
    uid = _safe_uid(u_uid)
    sid = str(session_id or "").strip()[:128]
    question = str(question or "").strip()[:_MAX_CONTENT]
    answer = str(answer or "").strip()[:_MAX_CONTENT]
    if not sid or not question:
        raise ValueError("session_id and question are required")

    now = _now()
    date_key = now[:10]
    title = question[:80]
    with _SHARD_LOCKS[_shard_index(uid)], _connect(_shard_path(uid)) as conn:
        owner = conn.execute(
            "SELECT u_uid FROM chat_sessions WHERE session_id = ?", (sid,)
        ).fetchone()
        if owner and owner["u_uid"] != uid:
            raise PermissionError("Session does not belong to this user")
        conn.execute(
            """INSERT INTO chat_sessions(session_id, u_uid, title, date_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET title = CASE
                 WHEN chat_sessions.title = 'New Chat' THEN excluded.title
                 ELSE chat_sessions.title END,
                 updated_at = excluded.updated_at""",
            (sid, uid, title, date_key, now, now),
        )
        conn.execute(
            "INSERT INTO chat_messages(session_id, u_uid, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (sid, uid, question, now),
        )
        if answer:
            import json as _json
            snap_json = _json.dumps(data_snapshot, ensure_ascii=False, default=str) if data_snapshot else None
            conn.execute(
                "INSERT INTO chat_messages(session_id, u_uid, role, content, data_snapshot, created_at) VALUES (?, ?, 'assistant', ?, ?, ?)",
                (sid, uid, answer, snap_json, now),
            )
        conn.execute(
            """DELETE FROM chat_messages WHERE session_id = ? AND id NOT IN
               (SELECT id FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?)""",
            (sid, sid, _MAX_MESSAGES),
        )
        conn.execute(
            """DELETE FROM chat_sessions WHERE u_uid = ? AND session_id NOT IN
               (SELECT session_id FROM chat_sessions WHERE u_uid = ? ORDER BY updated_at DESC LIMIT ?)""",
            (uid, uid, _MAX_SESSIONS),
        )
    return sid


def list_sessions(u_uid: str, search: str = "", limit: int = 40) -> List[Dict[str, Any]]:
    uid = _safe_uid(u_uid)
    search = str(search or "").strip()[:200]
    limit = max(1, min(int(limit or 40), 100))
    pattern = f"%{search}%"
    with _SHARD_LOCKS[_shard_index(uid)], _connect(_shard_path(uid)) as conn:
        rows = conn.execute(
            """SELECT DISTINCT s.* FROM chat_sessions s
               LEFT JOIN chat_messages m ON m.session_id = s.session_id AND m.u_uid = s.u_uid
               WHERE s.u_uid = ? AND (? = '' OR lower(s.title) LIKE lower(?) OR lower(m.content) LIKE lower(?))
               ORDER BY s.updated_at DESC LIMIT ?""",
            (uid, search, pattern, pattern, limit),
        ).fetchall()
        result = []
        for row in rows:
            messages = conn.execute(
                "SELECT role, content, data_snapshot, created_at FROM chat_messages WHERE session_id = ? AND u_uid = ? ORDER BY id ASC",
                (row["session_id"], uid),
            ).fetchall()
            result.append({
                "id": row["session_id"],
                "title": row["title"],
                "dateKey": row["date_key"],
                "created": row["created_at"],
                "updated": row["updated_at"],
                "messages": [
                {
                    "role": m["role"],
                    "content": m["content"],
                    "created_at": m["created_at"],
                    **({"data_snapshot": __import__("json").loads(m["data_snapshot"])} if ("data_snapshot" in m.keys() and m["data_snapshot"]) else {})
                }
                for m in messages
            ],
            })
        return result
