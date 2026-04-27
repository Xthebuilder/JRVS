"""Database operations for Jarvis AI Agent"""
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import asyncio
import aiosqlite
from config import DATABASE_PATH

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _open_db(path: str):
    """Open a DB connection with FK enforcement and WAL mode enabled.

    Use this instead of bare ``aiosqlite.connect()`` everywhere in this package
    so that PRAGMA settings are applied consistently on every connection.
    """
    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA journal_mode = WAL")
        yield db

class Database:
    def __init__(self, db_path: str = str(DATABASE_PATH)):
        self.db_path = db_path
        self._connection = None
        self._setup_complete = False

    async def initialize(self):
        """Initialize database and create tables"""
        if self._setup_complete:
            return

        async with _open_db(self.db_path) as db:
            await self._create_tables(db)
            await db.commit()
            await self._run_migrations(db)

        self._setup_complete = True

    async def _create_tables(self, db):
        """Create all necessary tables"""
        # Migration tracking — must exist before _run_migrations() is called
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT    UNIQUE NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Conversations table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_message TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                model_used TEXT NOT NULL,
                context_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                embedded INTEGER DEFAULT 0
            )
        """)

        # Documents table for scraped/ingested content
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                title TEXT,
                content TEXT NOT NULL,
                content_type TEXT DEFAULT 'text',
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                mem0_synced INTEGER DEFAULT 0
            )
        """)

        # Document chunks for RAG
        await db.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                chunk_text TEXT NOT NULL,
                chunk_index INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents (id)
            )
        """)

        # Models tracking
        await db.execute("""
            CREATE TABLE IF NOT EXISTS models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT UNIQUE NOT NULL,
                is_available BOOLEAN DEFAULT TRUE,
                last_used TIMESTAMP,
                usage_count INTEGER DEFAULT 0,
                avg_response_time REAL DEFAULT 0.0,
                metadata TEXT
            )
        """)

        # User preferences
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # FTS5 full-text index over document chunks (used for BM25 keyword search)
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_text,
                document_id UNINDEXED,
                chunk_index UNINDEXED
            )
        """)

        # Persistent map from FAISS vector index positions → text + metadata.
        # Replaces the pickle-based document_map for incremental, crash-safe persistence.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vector_map (
                faiss_idx  INTEGER PRIMARY KEY,
                text       TEXT    NOT NULL,
                metadata   TEXT    NOT NULL,
                added_at   REAL    NOT NULL
            )
        """)

        # Feedback table — flagged bad responses for training loop
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                response TEXT NOT NULL,
                note TEXT,
                processed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Training runs log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS training_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                examples_used INTEGER,
                final_loss REAL,
                model_path TEXT,
                status TEXT DEFAULT 'running'
            )
        """)

        # Calendar events (previously owned by core/calendar.py)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                title            TEXT      NOT NULL,
                description      TEXT,
                event_date       TIMESTAMP NOT NULL,
                reminder_minutes INTEGER   DEFAULT 0,
                completed        BOOLEAN   DEFAULT FALSE,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Goal state — persists long-running goal execution across restarts
        await db.execute("""
            CREATE TABLE IF NOT EXISTS goal_state (
                goal_id        TEXT PRIMARY KEY,
                status         TEXT NOT NULL DEFAULT 'idle',
                run_id         TEXT,
                plan_json      TEXT NOT NULL DEFAULT '[]',
                step_cursor    INTEGER NOT NULL DEFAULT 0,
                retry_count    INTEGER NOT NULL DEFAULT 0,
                last_error     TEXT DEFAULT '',
                started_at     TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                context_json   TEXT NOT NULL DEFAULT '{}'
            )
        """)

        # Pending CONFIRM-tier approvals waiting for Slack button response
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                action_id      TEXT PRIMARY KEY,
                goal_id        TEXT NOT NULL,
                run_id         TEXT NOT NULL,
                step_num       INTEGER NOT NULL,
                tool           TEXT NOT NULL,
                args_json      TEXT NOT NULL DEFAULT '{}',
                reason         TEXT DEFAULT '',
                slack_ts       TEXT,
                slack_channel  TEXT,
                status         TEXT NOT NULL DEFAULT 'awaiting',
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for performance
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_embedded ON conversations(embedded)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(url)")
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_url_unique ON documents(url) WHERE url IS NOT NULL AND url != ''")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_goal_state_status ON goal_state(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status)")

        # Marketing drafts — LLM-generated copy queue
        await db.execute("""
            CREATE TABLE IF NOT EXISTS marketing_drafts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id       TEXT    UNIQUE NOT NULL,
                brand        TEXT    NOT NULL,
                platform     TEXT    NOT NULL,
                topic        TEXT    NOT NULL,
                content_type TEXT    NOT NULL DEFAULT 'post',
                content      TEXT    NOT NULL,
                char_count   INTEGER NOT NULL DEFAULT 0,
                status       TEXT    NOT NULL DEFAULT 'draft',
                source       TEXT    NOT NULL DEFAULT 'manual',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_marketing_brand ON marketing_drafts(brand)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_marketing_platform ON marketing_drafts(platform)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_marketing_status ON marketing_drafts(status)")

        # Image generation jobs — ComfyUI queue
        await db.execute("""
            CREATE TABLE IF NOT EXISTS image_gen_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT    UNIQUE NOT NULL,
                prompt      TEXT    NOT NULL,
                model       TEXT    NOT NULL DEFAULT '',
                steps       INTEGER NOT NULL DEFAULT 20,
                cfg         REAL    NOT NULL DEFAULT 7.0,
                width       INTEGER NOT NULL DEFAULT 512,
                height      INTEGER NOT NULL DEFAULT 512,
                seed_used   INTEGER NOT NULL DEFAULT -1,
                output_path TEXT    NOT NULL DEFAULT '',
                status      TEXT    NOT NULL DEFAULT 'queued',
                error       TEXT    NOT NULL DEFAULT '',
                source      TEXT    NOT NULL DEFAULT 'manual',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_image_gen_status ON image_gen_jobs(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_image_gen_created ON image_gen_jobs(created_at)")

    # ------------------------------------------------------------------
    # Migration system
    # ------------------------------------------------------------------

    async def _run_migrations(self, db) -> None:
        """Run any pending schema migrations in order.

        Each migration is a coroutine that receives the open db connection.
        Migrations are recorded in schema_migrations by name and skipped on
        subsequent startups — making them safe to run at every initialize().
        """
        migrations = [
            ("m001_add_embedded_column", self._m001_add_embedded_column),
            ("m002_drop_conversations_embedding_vector", self._m002_drop_conversations_embedding_vector),
            ("m003_drop_chunks_embedding_vector", self._m003_drop_chunks_embedding_vector),
            ("m004_add_documents_mem0_synced", self._m004_add_documents_mem0_synced),
            ("m005_add_goal_state_tables", self._m005_add_goal_state_tables),
            ("m006_add_marketing_drafts", self._m006_add_marketing_drafts),
            ("m007_add_image_gen_jobs",   self._m007_add_image_gen_jobs),
        ]

        for name, fn in migrations:
            row = await db.execute(
                "SELECT id FROM schema_migrations WHERE name = ?", (name,)
            )
            if await row.fetchone() is not None:
                continue  # already applied
            logger.info("Applying migration %s", name)
            await fn(db)
            await db.execute(
                "INSERT INTO schema_migrations (name) VALUES (?)", (name,)
            )
            await db.commit()
            logger.info("Migration %s applied", name)

    @staticmethod
    async def _m001_add_embedded_column(db) -> None:
        """Backfill the embedded column on databases that predate it."""
        try:
            await db.execute(
                "ALTER TABLE conversations ADD COLUMN embedded INTEGER DEFAULT 0"
            )
        except Exception as err:
            if "duplicate column" not in str(err).lower():
                raise

    @staticmethod
    async def _m002_drop_conversations_embedding_vector(db) -> None:
        """Remove the never-written embedding_vector BLOB from conversations.

        Embeddings live in FAISS + vector_map; storing them as a per-row BLOB
        here was an early design that was superseded before it was ever used.
        """
        cur = await db.execute("PRAGMA table_info(conversations)")
        cols = [row[1] for row in await cur.fetchall()]
        if "embedding_vector" in cols:
            await db.execute("ALTER TABLE conversations DROP COLUMN embedding_vector")

    @staticmethod
    async def _m003_drop_chunks_embedding_vector(db) -> None:
        """Remove the never-written embedding_vector BLOB from document_chunks."""
        cur = await db.execute("PRAGMA table_info(document_chunks)")
        cols = [row[1] for row in await cur.fetchall()]
        if "embedding_vector" in cols:
            await db.execute("ALTER TABLE document_chunks DROP COLUMN embedding_vector")

    @staticmethod
    async def _m004_add_documents_mem0_synced(db) -> None:
        """Add mem0_synced flag to documents so the RAG backfill can track progress."""
        cur = await db.execute("PRAGMA table_info(documents)")
        cols = [row[1] for row in await cur.fetchall()]
        if "mem0_synced" not in cols:
            await db.execute(
                "ALTER TABLE documents ADD COLUMN mem0_synced INTEGER DEFAULT 0"
            )

    @staticmethod
    async def _m006_add_marketing_drafts(db) -> None:
        """Add marketing_drafts table for the marketing module."""
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='marketing_drafts'"
        )
        if await cur.fetchone() is not None:
            return
        await db.execute("""
            CREATE TABLE marketing_drafts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id       TEXT    UNIQUE NOT NULL,
                brand        TEXT    NOT NULL,
                platform     TEXT    NOT NULL,
                topic        TEXT    NOT NULL,
                content_type TEXT    NOT NULL DEFAULT 'post',
                content      TEXT    NOT NULL,
                char_count   INTEGER NOT NULL DEFAULT 0,
                status       TEXT    NOT NULL DEFAULT 'draft',
                source       TEXT    NOT NULL DEFAULT 'manual',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_marketing_brand ON marketing_drafts(brand)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_marketing_platform ON marketing_drafts(platform)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_marketing_status ON marketing_drafts(status)")

    @staticmethod
    async def _m007_add_image_gen_jobs(db) -> None:
        """Add image_gen_jobs table for the ComfyUI image generation module."""
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='image_gen_jobs'"
        )
        if await cur.fetchone() is not None:
            return
        await db.execute("""
            CREATE TABLE image_gen_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT    UNIQUE NOT NULL,
                prompt      TEXT    NOT NULL,
                model       TEXT    NOT NULL DEFAULT '',
                steps       INTEGER NOT NULL DEFAULT 20,
                cfg         REAL    NOT NULL DEFAULT 7.0,
                width       INTEGER NOT NULL DEFAULT 512,
                height      INTEGER NOT NULL DEFAULT 512,
                seed_used   INTEGER NOT NULL DEFAULT -1,
                output_path TEXT    NOT NULL DEFAULT '',
                status      TEXT    NOT NULL DEFAULT 'queued',
                error       TEXT    NOT NULL DEFAULT '',
                source      TEXT    NOT NULL DEFAULT 'manual',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_image_gen_status ON image_gen_jobs(status)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_image_gen_created ON image_gen_jobs(created_at)"
        )

    async def add_conversation(self, session_id: str, user_message: str,
                             ai_response: str, model_used: str, 
                             context_used: Optional[str] = None) -> int:
        """Add a conversation record"""
        async with _open_db(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO conversations (session_id, user_message, ai_response, model_used, context_used)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, user_message, ai_response, model_used, context_used))
            
            await db.commit()
            return cursor.lastrowid

    async def add_document(self, url: str, title: str, content: str,
                          content_type: str = 'text', metadata: Dict = None) -> int:
        """Add or update a document record.

        On URL conflict, merges existing metadata with the new metadata rather
        than silently replacing the entire row (preserving source annotations,
        tags, etc. set by earlier ingest passes).
        """
        new_meta = metadata or {}
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, metadata FROM documents WHERE url = ?", (url,)
            )
            existing = await cur.fetchone()

            if existing:
                # Merge: existing metadata wins on conflict, new metadata fills gaps
                old_meta = json.loads(existing["metadata"]) if existing["metadata"] else {}
                merged = {**new_meta, **old_meta}  # old values take precedence
                await db.execute(
                    """UPDATE documents
                          SET title = ?, content = ?, content_type = ?,
                              metadata = ?, mem0_synced = 0
                        WHERE id = ?""",
                    (title, content, content_type, json.dumps(merged), existing["id"]),
                )
                await db.commit()
                return existing["id"]

            cursor = await db.execute(
                """INSERT INTO documents (url, title, content, content_type, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (url, title, content, content_type, json.dumps(new_meta) if new_meta else None),
            )
            await db.commit()
            return cursor.lastrowid

    async def add_document_chunk(self, document_id: int, chunk_text: str,
                               chunk_index: int) -> int:
        """Add a document chunk and index it in the FTS5 table for keyword search."""
        async with _open_db(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO document_chunks (document_id, chunk_text, chunk_index)
                VALUES (?, ?, ?)
            """, (document_id, chunk_text, chunk_index))
            chunk_id = cursor.lastrowid

            # Mirror into FTS5 for BM25 keyword search
            await db.execute("""
                INSERT INTO chunks_fts (chunk_text, document_id, chunk_index)
                VALUES (?, ?, ?)
            """, (chunk_text, document_id, chunk_index))

            await db.commit()
            return chunk_id

    async def get_recent_conversations(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Get recent conversations for context"""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT user_message, ai_response, model_used, created_at
                FROM conversations 
                WHERE session_id = ?
                ORDER BY created_at DESC 
                LIMIT ?
            """, (session_id, limit))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_documents_by_query(self, query: str, limit: int = 5) -> List[Dict]:
        """Search documents by content using FTS5 index."""
        words = [re.sub(r'\W+', '', w) for w in query.split()]
        words = [w for w in words if len(w) >= 2]
        if not words:
            return []
        fts_query = ' '.join(words)
        try:
            async with _open_db(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT DISTINCT d.id, d.title, d.content, d.url, d.metadata
                    FROM chunks_fts f
                    JOIN documents d ON d.id = f.document_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY d.last_accessed DESC
                    LIMIT ?
                """, (fts_query, limit))
                rows = await cursor.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d['metadata'] = json.loads(d['metadata']) if d.get('metadata') else {}
                    result.append(d)
                return result
        except Exception as e:
            logger.warning("FTS search failed for %r: %s", fts_query, e)
            return []

    async def update_model_stats(self, model_name: str, response_time: float):
        """Update model usage statistics"""
        async with _open_db(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO models (model_name, last_used, usage_count, avg_response_time)
                VALUES (?, CURRENT_TIMESTAMP, 
                    COALESCE((SELECT usage_count FROM models WHERE model_name = ?), 0) + 1,
                    COALESCE((SELECT avg_response_time FROM models WHERE model_name = ?), 0) * 0.8 + ? * 0.2
                )
            """, (model_name, model_name, model_name, response_time))
            
            await db.commit()

    async def get_available_models(self) -> List[str]:
        """Get list of available models"""
        async with _open_db(self.db_path) as db:
            cursor = await db.execute("""
                SELECT model_name FROM models 
                WHERE is_available = TRUE
                ORDER BY usage_count DESC
            """)
            
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def set_preference(self, key: str, value: str):
        """Set user preference"""
        async with _open_db(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_preferences (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (key, value))
            
            await db.commit()

    async def get_preference(self, key: str, default: str = None) -> str:
        """Get user preference"""
        async with _open_db(self.db_path) as db:
            cursor = await db.execute("""
                SELECT value FROM user_preferences WHERE key = ?
            """, (key,))
            
            row = await cursor.fetchone()
            return row[0] if row else default

    async def check_document_exists(self, url: str) -> bool:
        """Check whether a URL has already been ingested (deduplication guard)"""
        if not url:
            return False
        async with _open_db(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM documents WHERE url = ? LIMIT 1", (url,)
            )
            row = await cursor.fetchone()
            return row is not None

    async def get_unsynced_documents(self, limit: int = 100) -> List[Dict]:
        """Return documents not yet ingested into the active RAG backend (Mem0/FAISS)."""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, url, title, content, content_type, metadata
                FROM documents
                WHERE mem0_synced = 0
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['metadata'] = json.loads(d['metadata']) if d.get('metadata') else {}
                result.append(d)
            return result

    async def mark_document_synced(self, document_id: int) -> None:
        """Mark a document as ingested into the active RAG backend."""
        async with _open_db(self.db_path) as db:
            await db.execute(
                "UPDATE documents SET mem0_synced = 1 WHERE id = ?", (document_id,)
            )
            await db.commit()

    async def get_unembedded_conversations(self, limit: int = 50) -> List[Dict]:
        """Return conversations that have not yet been embedded into FAISS"""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, session_id, user_message, ai_response, created_at
                FROM conversations
                WHERE embedded = 0
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def mark_conversation_embedded(self, conversation_id: int) -> None:
        """Mark a conversation turn as embedded in the FAISS index"""
        async with _open_db(self.db_path) as db:
            await db.execute(
                "UPDATE conversations SET embedded = 1 WHERE id = ?",
                (conversation_id,)
            )
            await db.commit()

    async def get_recent_cross_session_conversations(self, limit: int = 10) -> List[Dict]:
        """Fetch recent conversations across ALL sessions (for fallback context)"""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT user_message, ai_response, model_used, session_id, created_at
                FROM conversations
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # FTS5 keyword search
    # ------------------------------------------------------------------

    async def fts_search_chunks(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Full-text BM25 keyword search over document chunks using SQLite FTS5.
        Returns results ordered by relevance (best first).
        """
        # Tokenise: strip non-word chars so we don't confuse FTS5's query parser
        words = [re.sub(r'\W+', '', w) for w in query.split()]
        words = [w for w in words if len(w) >= 2]
        if not words:
            return []
        fts_query = ' '.join(words)

        try:
            async with _open_db(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                # `rank` is SQLite FTS5's built-in BM25 score (lower = more relevant)
                cursor = await db.execute("""
                    SELECT f.chunk_text, f.document_id, f.chunk_index,
                           d.title, d.url, d.metadata
                    FROM chunks_fts f
                    LEFT JOIN documents d ON d.id = f.document_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, limit))
                rows = await cursor.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d['metadata'] = json.loads(d['metadata']) if d.get('metadata') else {}
                    result.append(d)
                return result
        except Exception as e:
            logger.warning("FTS search failed for %r: %s", fts_query, e)
            return []

    # ------------------------------------------------------------------
    # Vector map persistence (replaces pickle-based document_map)
    # ------------------------------------------------------------------

    async def load_vector_map(self) -> Dict:
        """Load the full FAISS-position → text/metadata map from SQLite."""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT faiss_idx, text, metadata, added_at FROM vector_map"
            )
            rows = await cursor.fetchall()
            return {
                row['faiss_idx']: {
                    'text':     row['text'],
                    'metadata': json.loads(row['metadata']),
                    'added_at': row['added_at'],
                }
                for row in rows
            }

    async def save_vector_map_batch(self, entries: List[Tuple]) -> None:
        """
        Persist multiple (faiss_idx, text, metadata_json, added_at) tuples at once.
        More efficient than individual inserts during migration or bulk ingestion.
        """
        async with _open_db(self.db_path) as db:
            await db.executemany("""
                INSERT OR REPLACE INTO vector_map (faiss_idx, text, metadata, added_at)
                VALUES (?, ?, ?, ?)
            """, entries)
            await db.commit()

    async def save_vector_map_entry(
        self, faiss_idx: int, text: str, metadata: dict, added_at: float
    ) -> None:
        """Persist a single vector_map entry to SQLite."""
        async with _open_db(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO vector_map (faiss_idx, text, metadata, added_at)
                VALUES (?, ?, ?, ?)
            """, (faiss_idx, text, json.dumps(metadata), added_at))
            await db.commit()

    async def clear_vector_map(self) -> None:
        """Delete all vector_map entries (called when rebuilding the FAISS index)."""
        async with _open_db(self.db_path) as db:
            await db.execute("DELETE FROM vector_map")
            await db.commit()

    async def delete_vector_map_entries(self, faiss_indices: List[int]) -> None:
        """Remove specific entries from vector_map (used during document removal)."""
        async with _open_db(self.db_path) as db:
            await db.executemany(
                "DELETE FROM vector_map WHERE faiss_idx = ?",
                [(i,) for i in faiss_indices]
            )
            await db.commit()

    async def log_feedback(self, question: str, response: str, note: str = "") -> int:
        """Log a bad response for the training feedback loop."""
        async with _open_db(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO feedback (question, response, note) VALUES (?, ?, ?)",
                (question, response, note)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_pending_feedback(self, limit: int = 100) -> List[Dict]:
        """Get unprocessed feedback items for the training loop."""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM feedback WHERE processed = 0 ORDER BY created_at ASC LIMIT ?",
                (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def mark_feedback_processed(self, feedback_id: int) -> None:
        """Mark a feedback item as converted to training data."""
        async with _open_db(self.db_path) as db:
            await db.execute(
                "UPDATE feedback SET processed = 1 WHERE id = ?", (feedback_id,)
            )
            await db.commit()

    async def log_training_run(self, examples_used: int, final_loss: float,
                               model_path: str, status: str = "completed") -> None:
        """Log a completed training run."""
        async with _open_db(self.db_path) as db:
            await db.execute("""
                INSERT INTO training_runs (completed_at, examples_used, final_loss, model_path, status)
                VALUES (CURRENT_TIMESTAMP, ?, ?, ?, ?)
            """, (examples_used, final_loss, model_path, status))
            await db.commit()

    @staticmethod
    async def _m005_add_goal_state_tables(db) -> None:
        """Add goal_state and pending_approvals tables for the unified agent loop."""
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='goal_state'")
        if not await cur.fetchone():
            await db.execute("""
                CREATE TABLE goal_state (
                    goal_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'idle',
                    run_id TEXT, plan_json TEXT NOT NULL DEFAULT '[]',
                    step_cursor INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT DEFAULT '', started_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    context_json TEXT NOT NULL DEFAULT '{}'
                )
            """)
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pending_approvals'")
        if not await cur.fetchone():
            await db.execute("""
                CREATE TABLE pending_approvals (
                    action_id TEXT PRIMARY KEY, goal_id TEXT NOT NULL,
                    run_id TEXT NOT NULL, step_num INTEGER NOT NULL,
                    tool TEXT NOT NULL, args_json TEXT NOT NULL DEFAULT '{}',
                    reason TEXT DEFAULT '', slack_ts TEXT, slack_channel TEXT,
                    status TEXT NOT NULL DEFAULT 'awaiting',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    # ------------------------------------------------------------------
    # Goal state
    # ------------------------------------------------------------------

    async def upsert_goal_state(self, goal_id: str, fields: dict) -> None:
        """Insert or partially update a goal_state row."""
        fields["updated_at"] = datetime.utcnow().isoformat()
        async with _open_db(self.db_path) as db:
            cur = await db.execute("SELECT goal_id FROM goal_state WHERE goal_id = ?", (goal_id,))
            existing = await cur.fetchone()
            if existing:
                set_clause = ", ".join(f"{k} = ?" for k in fields)
                await db.execute(
                    f"UPDATE goal_state SET {set_clause} WHERE goal_id = ?",
                    [*fields.values(), goal_id],
                )
            else:
                fields["goal_id"] = goal_id
                cols = ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in fields)
                await db.execute(
                    f"INSERT INTO goal_state ({cols}) VALUES ({placeholders})",
                    list(fields.values()),
                )
            await db.commit()

    async def get_goal_state(self, goal_id: str) -> Optional[Dict]:
        """Return the goal_state row for goal_id, or None."""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM goal_state WHERE goal_id = ?", (goal_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_goal_states(self, status: Optional[str] = None) -> List[Dict]:
        """List all goal_state rows, optionally filtered by status."""
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cur = await db.execute(
                    "SELECT * FROM goal_state WHERE status = ? ORDER BY updated_at DESC", (status,)
                )
            else:
                cur = await db.execute("SELECT * FROM goal_state ORDER BY updated_at DESC")
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def count_unprocessed_feedback(self) -> int:
        """Count feedback rows not yet processed by the training loop."""
        async with _open_db(self.db_path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM feedback WHERE processed = 0")
            row = await cur.fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # Pending approvals (CONFIRM-tier Slack buttons)
    # ------------------------------------------------------------------

    async def save_pending_approval(self, row: dict) -> None:
        async with _open_db(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO pending_approvals
                (action_id, goal_id, run_id, step_num, tool, args_json, reason,
                 slack_ts, slack_channel, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["action_id"], row["goal_id"], row["run_id"], row["step_num"],
                row["tool"], row["args_json"], row.get("reason", ""),
                row.get("slack_ts"), row.get("slack_channel"), "awaiting",
            ))
            await db.commit()

    async def get_pending_approval(self, action_id: str) -> Optional[Dict]:
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM pending_approvals WHERE action_id = ?", (action_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def update_approval_status(self, action_id: str, status: str) -> None:
        async with _open_db(self.db_path) as db:
            await db.execute(
                "UPDATE pending_approvals SET status = ? WHERE action_id = ?",
                (status, action_id),
            )
            await db.commit()

    async def cleanup_old_data(self, days: int = 30):
        """Clean up old conversation data"""
        async with _open_db(self.db_path) as db:
            await db.execute("""
                DELETE FROM conversations 
                WHERE created_at < datetime('now', '-' || ? || ' days')
            """, (days,))
            
            await db.commit()

    # ------------------------------------------------------------------
    # Marketing drafts
    # ------------------------------------------------------------------

    async def save_marketing_draft(
        self,
        job_id: str,
        brand: str,
        platform: str,
        topic: str,
        content_type: str,
        content: str,
        source: str = "manual",
    ) -> int:
        """Insert or replace a marketing draft. Returns the row id."""
        async with _open_db(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT OR REPLACE INTO marketing_drafts
                    (job_id, brand, platform, topic, content_type, content, char_count, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, brand, platform, topic, content_type, content, len(content), source),
            )
            await db.commit()
            return cursor.lastrowid

    async def list_marketing_drafts(
        self,
        brand: Optional[str] = None,
        platform: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """Return recent marketing drafts, newest first, optionally filtered."""
        clauses: List[str] = []
        params: List = []
        if brand:
            clauses.append("brand = ?")
            params.append(brand)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"SELECT * FROM marketing_drafts {where} ORDER BY created_at DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Image generation jobs
    # ------------------------------------------------------------------

    async def upsert_image_job(self, job_id: str, fields: dict) -> None:
        """Insert or partially update an image_gen_jobs row.

        On insert, job_id is added to fields automatically.
        On update, only the supplied keys are changed — other columns untouched.
        """
        async with _open_db(self.db_path) as db:
            cur = await db.execute(
                "SELECT job_id FROM image_gen_jobs WHERE job_id = ?", (job_id,)
            )
            existing = await cur.fetchone()
            if existing:
                set_clause = ", ".join(f"{k} = ?" for k in fields)
                await db.execute(
                    f"UPDATE image_gen_jobs SET {set_clause} WHERE job_id = ?",
                    [*fields.values(), job_id],
                )
            else:
                fields = {"job_id": job_id, **fields}
                cols   = ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in fields)
                await db.execute(
                    f"INSERT INTO image_gen_jobs ({cols}) VALUES ({placeholders})",
                    list(fields.values()),
                )
            await db.commit()

    async def list_image_jobs(
        self,
        status: Optional[str] = None,
        limit:  int = 10,
    ) -> List[Dict]:
        """Return recent image jobs, newest first, optionally filtered by status."""
        params: List = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(limit)
        async with _open_db(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"SELECT * FROM image_gen_jobs {where} "
                f"ORDER BY created_at DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


# Global database instance
db = Database()