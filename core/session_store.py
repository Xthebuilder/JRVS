"""Unified session history store backed by SQLite (aiosqlite).

All entry points (API server, CLI, voice via API) read and write conversation
history through this single module.  The ``conversations`` table in
core/database.py is *not* replaced — it serves a different purpose (RAG
embedding source + long-term analytics).  This module manages the hot
conversation window used to build LLM context.
"""

import json
import logging
from typing import Optional

import aiosqlite

from config import CONVERSATION_HISTORY_TURNS, DATABASE_PATH
from core.database import _open_db

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS session_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    role       TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT    NOT NULL,
    metadata   TEXT    NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_session_messages_lookup
    ON session_messages (session_id, created_at DESC);
"""


class SessionStore:
    """Async SQLite-backed session history shared by all JRVS entry points."""

    def __init__(self) -> None:
        self._db_path: str = str(DATABASE_PATH)
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Ensure the schema exists."""
        if self._initialized:
            return
        async with _open_db(self._db_path) as db:
            for statement in _SCHEMA_SQL.strip().split(";"):
                statement = statement.strip()
                if statement:
                    await db.execute(statement)
            await db.commit()
        self._initialized = True
        logger.info("Session store initialized (table session_messages ready)")

    async def close(self) -> None:
        """No-op: aiosqlite connections are per-operation, nothing to close."""
        self._initialized = False

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> int:
        """Insert a single message and return its rowid."""
        meta_json = json.dumps(metadata) if metadata else "{}"
        async with _open_db(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO session_messages (session_id, role, content, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, meta_json),
            )
            await db.commit()
            return cursor.lastrowid

    async def add_turn(
        self,
        session_id: str,
        user_msg: str,
        assistant_msg: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """Insert a user/assistant pair as two rows in a single transaction."""
        meta_json = json.dumps(metadata) if metadata else "{}"
        async with _open_db(self._db_path) as db:
            await db.execute(
                "INSERT INTO session_messages (session_id, role, content, metadata) VALUES (?, 'user', ?, ?)",
                (session_id, user_msg, meta_json),
            )
            await db.execute(
                "INSERT INTO session_messages (session_id, role, content, metadata) VALUES (?, 'assistant', ?, ?)",
                (session_id, assistant_msg, meta_json),
            )
            await db.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_recent(
        self,
        session_id: str,
        limit: int = CONVERSATION_HISTORY_TURNS,
    ) -> list[dict]:
        """Return the last *limit* turns in chronological order (oldest first).

        Each turn is 2 rows, so we fetch ``limit * 2`` rows newest-first then reverse.
        """
        async with _open_db(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT role, content
                FROM session_messages
                WHERE session_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (session_id, limit * 2),
            )
            rows = await cursor.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def get_recent_as_pairs(
        self,
        session_id: str,
        limit: int = CONVERSATION_HISTORY_TURNS,
    ) -> list[dict]:
        """Return recent history as ``[{"user": ..., "assistant": ...}]``.

        This is the format expected by
        ``ollama_client.generate(conversation_history=...)``.
        """
        flat = await self.get_recent(session_id, limit=limit)
        pairs: list[dict] = []
        i = 0
        while i < len(flat) - 1:
            if flat[i]["role"] == "user" and flat[i + 1]["role"] == "assistant":
                pairs.append({
                    "user": flat[i]["content"],
                    "assistant": flat[i + 1]["content"],
                })
                i += 2
            else:
                i += 1
        return pairs

    async def count(self, session_id: str) -> int:
        """Return the total number of messages for a session."""
        async with _open_db(self._db_path) as db:
            cursor = await db.execute(
                "SELECT count(*) FROM session_messages WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0


# Global singleton — matches the pattern used by ``core.database.db``
session_store = SessionStore()
