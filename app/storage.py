"""SQLite storage: conversation history per chat + WHOOP token cache."""
import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

from app.config import Config


def init_db():
    """Create tables if they don't exist."""
    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat_created
                ON messages(chat_id, created_at);

            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )


@contextmanager
def _conn():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------- Conversation history ----------

def add_message(chat_id: int, role: str, content: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )


def get_recent_messages(chat_id: int, limit: int = 20) -> list[dict]:
    """Return the last N messages for a chat, oldest first."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_history(chat_id: int):
    with _conn() as c:
        c.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))


# ---------- Generic KV (used for WHOOP access token cache) ----------

def kv_set(key: str, value: dict):
    with _conn() as c:
        c.execute(
            "INSERT INTO kv (key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(value)),
        )


def kv_get(key: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None
