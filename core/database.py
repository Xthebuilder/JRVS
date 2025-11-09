"""Database operations for Jarvis AI Agent"""
import sqlite3
import json
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
                embedding_vector BLOB
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

        # Create indexes for performance
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_url ON documents(url)")
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
        """Add a document chunk"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO document_chunks (document_id, chunk_text, chunk_index)
                VALUES (?, ?, ?)
            """, (document_id, chunk_text, chunk_index))
            
            await db.commit()
            return cursor.lastrowid

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

    async def cleanup_old_data(self, days: int = 30):
        """Clean up old conversation data"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                DELETE FROM conversations 
                WHERE created_at < datetime('now', '-{} days')
            """.format(days))
            
            await db.commit()

# Global database instance
db = Database()