"""Database operations for Jarvis AI Agent"""
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import asyncio
import aiosqlite
from config import DATABASE_PATH

class Database:
    def __init__(self, db_path: str = str(DATABASE_PATH)):
        self.db_path = db_path
        self._connection = None
        self._setup_complete = False

    async def initialize(self):
        """Initialize database and create tables"""
        if self._setup_complete:
            return
            
        async with aiosqlite.connect(self.db_path) as db:
            await self._create_tables(db)
            await db.commit()
        
        self._setup_complete = True

    async def _create_tables(self, db):
        """Create all necessary tables"""
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
                embedding_vector BLOB,
                embedded INTEGER DEFAULT 0
            )
        """)

        # Add embedded column to existing tables that predate this migration
        try:
            await db.execute("ALTER TABLE conversations ADD COLUMN embedded INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass  # Column already exists

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
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Document chunks for RAG
        await db.execute("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                chunk_text TEXT NOT NULL,
                chunk_index INTEGER,
                embedding_vector BLOB,
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

        # Create indexes for performance
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_embedded ON conversations(embedded)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(url)")
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_url_unique ON documents(url) WHERE url IS NOT NULL AND url != ''")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id)")

    async def add_conversation(self, session_id: str, user_message: str, 
                             ai_response: str, model_used: str, 
                             context_used: Optional[str] = None) -> int:
        """Add a conversation record"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO conversations (session_id, user_message, ai_response, model_used, context_used)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, user_message, ai_response, model_used, context_used))
            
            await db.commit()
            return cursor.lastrowid

    async def add_document(self, url: str, title: str, content: str, 
                          content_type: str = 'text', metadata: Dict = None) -> int:
        """Add a document record"""
        metadata_json = json.dumps(metadata) if metadata else None
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT OR REPLACE INTO documents (url, title, content, content_type, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (url, title, content, content_type, metadata_json))
            
            await db.commit()
            return cursor.lastrowid

    async def add_document_chunk(self, document_id: int, chunk_text: str,
                               chunk_index: int) -> int:
        """Add a document chunk and index it in the FTS5 table for keyword search."""
        async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
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
        """Search documents by content (basic text search)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, title, content, url, metadata
                FROM documents 
                WHERE content LIKE ? OR title LIKE ?
                ORDER BY last_accessed DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_model_stats(self, model_name: str, response_time: float):
        """Update model usage statistics"""
        async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT model_name FROM models 
                WHERE is_available = TRUE
                ORDER BY usage_count DESC
            """)
            
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def set_preference(self, key: str, value: str):
        """Set user preference"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_preferences (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (key, value))
            
            await db.commit()

    async def get_preference(self, key: str, default: str = None) -> str:
        """Get user preference"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT value FROM user_preferences WHERE key = ?
            """, (key,))
            
            row = await cursor.fetchone()
            return row[0] if row else default

    async def check_document_exists(self, url: str) -> bool:
        """Check whether a URL has already been ingested (deduplication guard)"""
        if not url:
            return False
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM documents WHERE url = ? LIMIT 1", (url,)
            )
            row = await cursor.fetchone()
            return row is not None

    async def get_unembedded_conversations(self, limit: int = 50) -> List[Dict]:
        """Return conversations that have not yet been embedded into FAISS"""
        async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE conversations SET embedded = 1 WHERE id = ?",
                (conversation_id,)
            )
            await db.commit()

    async def get_recent_cross_session_conversations(self, limit: int = 10) -> List[Dict]:
        """Fetch recent conversations across ALL sessions (for fallback context)"""
        async with aiosqlite.connect(self.db_path) as db:
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
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                # `rank` is SQLite FTS5's built-in BM25 score (lower = more relevant)
                cursor = await db.execute("""
                    SELECT f.chunk_text, f.document_id, f.chunk_index,
                           d.title, d.url
                    FROM chunks_fts f
                    LEFT JOIN documents d ON d.id = f.document_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, limit))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[FTS] Search failed for '{fts_query}': {e}")
            return []

    # ------------------------------------------------------------------
    # Vector map persistence (replaces pickle-based document_map)
    # ------------------------------------------------------------------

    async def load_vector_map(self) -> Dict:
        """Load the full FAISS-position → text/metadata map from SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
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
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany("""
                INSERT OR REPLACE INTO vector_map (faiss_idx, text, metadata, added_at)
                VALUES (?, ?, ?, ?)
            """, entries)
            await db.commit()

    async def save_vector_map_entry(
        self, faiss_idx: int, text: str, metadata: dict, added_at: float
    ) -> None:
        """Persist a single vector_map entry to SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO vector_map (faiss_idx, text, metadata, added_at)
                VALUES (?, ?, ?, ?)
            """, (faiss_idx, text, json.dumps(metadata), added_at))
            await db.commit()

    async def clear_vector_map(self) -> None:
        """Delete all vector_map entries (called when rebuilding the FAISS index)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM vector_map")
            await db.commit()

    async def delete_vector_map_entries(self, faiss_indices: List[int]) -> None:
        """Remove specific entries from vector_map (used during document removal)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                "DELETE FROM vector_map WHERE faiss_idx = ?",
                [(i,) for i in faiss_indices]
            )
            await db.commit()

    async def cleanup_old_data(self, days: int = 30):
        """Clean up old conversation data"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                DELETE FROM conversations 
                WHERE created_at < datetime('now', '-' || ? || ' days')
            """, (days,))
            
            await db.commit()

# Global database instance
db = Database()