"""Simple calendar/reminder system for Jarvis"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import aiosqlite
from config import DATABASE_PATH

class Calendar:
    def __init__(self, db_path: str = str(DATABASE_PATH)):
        self.db_path = db_path

    async def initialize(self):
        """Create calendar tables"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    event_date TIMESTAMP NOT NULL,
                    reminder_minutes INTEGER DEFAULT 0,
                    completed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date)")
            await db.commit()

    async def add_event(self, title: str, event_date: datetime,
                       description: str = "", reminder_minutes: int = 0) -> int:
        """Add a calendar event"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO events (title, description, event_date, reminder_minutes)
                VALUES (?, ?, ?, ?)
            """, (title, description, event_date.isoformat(), reminder_minutes))
            await db.commit()
            return cursor.lastrowid

    async def get_upcoming_events(self, days: int = 7) -> List[Dict]:
        """Get upcoming events"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            end_date = (datetime.now() + timedelta(days=days)).isoformat()
            cursor = await db.execute("""
                SELECT id, title, description, event_date, reminder_minutes, completed
                FROM events
                WHERE event_date BETWEEN datetime('now') AND ?
                AND completed = FALSE
                ORDER BY event_date ASC
            """, (end_date,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_today_events(self) -> List[Dict]:
        """Get today's events"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, title, description, event_date, reminder_minutes, completed
                FROM events
                WHERE date(event_date) = date('now')
                AND completed = FALSE
                ORDER BY event_date ASC
            """)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def mark_completed(self, event_id: int):
        """Mark event as completed"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE events SET completed = TRUE WHERE id = ?", (event_id,))
            await db.commit()

    async def delete_event(self, event_id: int):
        """Delete an event"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM events WHERE id = ?", (event_id,))
            await db.commit()

# Global calendar instance
calendar = Calendar()
