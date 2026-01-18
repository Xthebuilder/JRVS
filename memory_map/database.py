"""Database operations for Mind Map Memory Module"""
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import aiosqlite
from config import DATABASE_PATH


class MindMapDatabase:
    """Database handler for mind map related operations"""
    
    def __init__(self, db_path: str = str(DATABASE_PATH)):
        self.db_path = db_path
        self._initialized = False

    async def initialize(self):
        """Initialize mind map tables"""
        if self._initialized:
            return
            
        async with aiosqlite.connect(self.db_path) as db:
            await self._create_mindmap_tables(db)
            await db.commit()
        
        self._initialized = True

    async def _create_mindmap_tables(self, db):
        """Create all mind map related tables"""
        
        # Topics extracted from conversations
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_name TEXT NOT NULL UNIQUE,
                category TEXT,
                first_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                mention_count INTEGER DEFAULT 1,
                embedding BLOB
            )
        """)

        # Relationships between topics
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topic_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id_1 INTEGER,
                topic_id_2 INTEGER,
                strength REAL DEFAULT 0.0,
                co_occurrence_count INTEGER DEFAULT 0,
                relationship_type TEXT DEFAULT 'related',
                FOREIGN KEY (topic_id_1) REFERENCES topics(id),
                FOREIGN KEY (topic_id_2) REFERENCES topics(id),
                UNIQUE(topic_id_1, topic_id_2)
            )
        """)

        # Link conversations to topics
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversation_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                topic_id INTEGER,
                relevance_score REAL DEFAULT 0.0,
                mentioned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (topic_id) REFERENCES topics(id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)

        # Mind map snapshots (save different views)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mindmap_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                graph_data TEXT,
                description TEXT
            )
        """)

        # Track mindmap initialization status
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mindmap_status (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for performance
        await db.execute("CREATE INDEX IF NOT EXISTS idx_topics_name ON topics(topic_name)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_topics_category ON topics(category)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_topic_rel_1 ON topic_relationships(topic_id_1)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_topic_rel_2 ON topic_relationships(topic_id_2)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conv_topics_conv ON conversation_topics(conversation_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conv_topics_topic ON conversation_topics(topic_id)")

    async def is_mindmap_initialized(self) -> bool:
        """Check if mindmap has been initialized with topic extraction"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM mindmap_status WHERE key = 'initialized'"
            )
            row = await cursor.fetchone()
            return row is not None and row[0] == 'true'

    async def mark_mindmap_initialized(self):
        """Mark mindmap as initialized"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO mindmap_status (key, value, updated_at)
                VALUES ('initialized', 'true', CURRENT_TIMESTAMP)
            """)
            await db.commit()

    async def insert_or_update_topic(self, topic_data: Dict) -> int:
        """Insert a new topic or update existing one"""
        topic_name = topic_data['topic']
        category = topic_data.get('category', 'other')
        embedding = topic_data.get('embedding')
        
        # Convert numpy array to bytes if needed
        embedding_bytes = None
        if embedding is not None:
            import numpy as np
            if isinstance(embedding, np.ndarray):
                embedding_bytes = embedding.tobytes()
            else:
                embedding_bytes = embedding
        
        async with aiosqlite.connect(self.db_path) as db:
            # Try to get existing topic
            cursor = await db.execute(
                "SELECT id, mention_count FROM topics WHERE topic_name = ?",
                (topic_name,)
            )
            existing = await cursor.fetchone()
            
            if existing:
                # Update existing topic
                topic_id = existing[0]
                new_count = existing[1] + 1
                await db.execute("""
                    UPDATE topics 
                    SET mention_count = ?, last_mentioned = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_count, topic_id))
            else:
                # Insert new topic
                cursor = await db.execute("""
                    INSERT INTO topics (topic_name, category, embedding)
                    VALUES (?, ?, ?)
                """, (topic_name, category, embedding_bytes))
                topic_id = cursor.lastrowid
            
            await db.commit()
            return topic_id

    async def link_conversation_topic(self, conversation_id: int, topic_id: int, 
                                      relevance_score: float):
        """Link a conversation to a topic"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO conversation_topics 
                (conversation_id, topic_id, relevance_score)
                VALUES (?, ?, ?)
            """, (conversation_id, topic_id, relevance_score))
            await db.commit()

    async def get_all_topics(self, limit: int = 100) -> List[Dict]:
        """Get all topics ordered by mention count"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, topic_name, category, first_mentioned, last_mentioned,
                       mention_count, embedding
                FROM topics
                ORDER BY mention_count DESC
                LIMIT ?
            """, (limit,))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_topic_by_id(self, topic_id: int) -> Optional[Dict]:
        """Get a topic by its ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM topics WHERE id = ?", (topic_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def search_topics(self, search_term: str, limit: int = 20) -> List[Dict]:
        """Search topics by name"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, topic_name, category, mention_count
                FROM topics
                WHERE topic_name LIKE ?
                ORDER BY mention_count DESC
                LIMIT ?
            """, (f"%{search_term}%", limit))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_topic_co_occurrence(self, topic_id_1: int, topic_id_2: int) -> int:
        """Get how often two topics appear in the same conversation"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT COUNT(DISTINCT ct1.conversation_id)
                FROM conversation_topics ct1
                JOIN conversation_topics ct2 ON ct1.conversation_id = ct2.conversation_id
                WHERE ct1.topic_id = ? AND ct2.topic_id = ?
            """, (topic_id_1, topic_id_2))
            
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def topics_in_same_conversation(self, topic_id_1: int, topic_id_2: int) -> bool:
        """Check if two topics appear in the same conversation"""
        co_occurrence = await self.get_topic_co_occurrence(topic_id_1, topic_id_2)
        return co_occurrence > 0

    async def store_topic_relationship(self, topic_id_1: int, topic_id_2: int, 
                                       strength: float, relationship_type: str = 'related'):
        """Store or update relationship between two topics"""
        # Ensure consistent ordering
        if topic_id_1 > topic_id_2:
            topic_id_1, topic_id_2 = topic_id_2, topic_id_1
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO topic_relationships 
                (topic_id_1, topic_id_2, strength, co_occurrence_count, relationship_type)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(topic_id_1, topic_id_2) DO UPDATE SET
                    strength = excluded.strength,
                    co_occurrence_count = co_occurrence_count + 1,
                    relationship_type = excluded.relationship_type
            """, (topic_id_1, topic_id_2, strength, relationship_type))
            await db.commit()

    async def get_topic_relationships(self, min_strength: float = 0.0) -> List[Dict]:
        """Get all topic relationships above minimum strength"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT tr.*, 
                       t1.topic_name as topic_1_name,
                       t2.topic_name as topic_2_name
                FROM topic_relationships tr
                JOIN topics t1 ON tr.topic_id_1 = t1.id
                JOIN topics t2 ON tr.topic_id_2 = t2.id
                WHERE tr.strength >= ?
                ORDER BY tr.strength DESC
            """, (min_strength,))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_related_topics(self, topic_id: int, limit: int = 10) -> List[Dict]:
        """Get topics related to a specific topic"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT t.id, t.topic_name, t.category, t.mention_count, tr.strength
                FROM topics t
                JOIN topic_relationships tr ON 
                    (tr.topic_id_1 = t.id AND tr.topic_id_2 = ?) OR
                    (tr.topic_id_2 = t.id AND tr.topic_id_1 = ?)
                WHERE t.id != ?
                ORDER BY tr.strength DESC
                LIMIT ?
            """, (topic_id, topic_id, topic_id, limit))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_conversations_for_topic(self, topic_id: int, limit: int = 10) -> List[Dict]:
        """Get conversations that contain a specific topic"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT c.id, c.user_message, c.ai_response, c.created_at, 
                       ct.relevance_score
                FROM conversations c
                JOIN conversation_topics ct ON c.id = ct.conversation_id
                WHERE ct.topic_id = ?
                ORDER BY c.created_at DESC
                LIMIT ?
            """, (topic_id, limit))
            
            rows = await cursor.fetchall()
            
            result = []
            for row in rows:
                # Create a summary from the user message
                user_msg = row['user_message'][:100] + '...' if len(row['user_message']) > 100 else row['user_message']
                result.append({
                    'id': row['id'],
                    'summary': user_msg,
                    'date': row['created_at'],
                    'relevance': row['relevance_score']
                })
            
            return result

    async def save_mindmap_snapshot(self, name: str, graph_data: str, 
                                    description: str = "") -> int:
        """Save a snapshot of the current mind map state"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO mindmap_snapshots (snapshot_name, graph_data, description)
                VALUES (?, ?, ?)
            """, (name, graph_data, description))
            
            await db.commit()
            return cursor.lastrowid

    async def get_all_snapshots(self) -> List[Dict]:
        """Get all saved snapshots"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, snapshot_name, created_at, description
                FROM mindmap_snapshots
                ORDER BY created_at DESC
            """)
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_snapshot(self, snapshot_id: int) -> Optional[Dict]:
        """Get a specific snapshot by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM mindmap_snapshots WHERE id = ?", (snapshot_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_recent_conversations(self, limit: int = 100) -> List[Dict]:
        """Get recent conversations from the main conversations table"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, session_id, user_message, ai_response, created_at
                FROM conversations
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                result.append({
                    'id': row['id'],
                    'session_id': row['session_id'],
                    'text': f"User: {row['user_message']}\n\nAssistant: {row['ai_response']}",
                    'created_at': row['created_at']
                })
            return result

    async def get_unprocessed_conversations(self, limit: int = 50) -> List[Dict]:
        """Get conversations that haven't been processed for topics yet"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT c.id, c.session_id, c.user_message, c.ai_response, c.created_at
                FROM conversations c
                LEFT JOIN conversation_topics ct ON c.id = ct.conversation_id
                WHERE ct.id IS NULL
                ORDER BY c.created_at DESC
                LIMIT ?
            """, (limit,))
            
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                result.append({
                    'id': row['id'],
                    'session_id': row['session_id'],
                    'text': f"User: {row['user_message']}\n\nAssistant: {row['ai_response']}",
                    'created_at': row['created_at']
                })
            return result

    async def get_graph_statistics(self) -> Dict:
        """Get statistics about the topic graph"""
        async with aiosqlite.connect(self.db_path) as db:
            # Total topics
            cursor = await db.execute("SELECT COUNT(*) FROM topics")
            total_topics = (await cursor.fetchone())[0]
            
            # Total connections
            cursor = await db.execute("SELECT COUNT(*) FROM topic_relationships")
            total_connections = (await cursor.fetchone())[0]
            
            # Average mentions per topic
            cursor = await db.execute("SELECT AVG(mention_count) FROM topics")
            avg_mentions = (await cursor.fetchone())[0] or 0
            
            # Top category
            cursor = await db.execute("""
                SELECT category, COUNT(*) as count
                FROM topics
                GROUP BY category
                ORDER BY count DESC
                LIMIT 1
            """)
            top_category_row = await cursor.fetchone()
            top_category = top_category_row[0] if top_category_row else 'unknown'
            
            # Total conversations processed
            cursor = await db.execute(
                "SELECT COUNT(DISTINCT conversation_id) FROM conversation_topics"
            )
            conversations_processed = (await cursor.fetchone())[0]
            
            return {
                'total_topics': total_topics,
                'total_connections': total_connections,
                'avg_mentions': round(avg_mentions, 2),
                'top_category': top_category,
                'conversations_processed': conversations_processed
            }


# Global mindmap database instance
mindmap_db = MindMapDatabase()
