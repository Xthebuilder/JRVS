"""Simple calendar/reminder system for Jarvis"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import aiosqlite
import calendar as pycal
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

    async def get_month_events(self, year: int, month: int) -> Dict[int, List[Dict]]:
        """Get events for a specific month, grouped by day"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            start_date = datetime(year, month, 1)

            # Get last day of month
            last_day = pycal.monthrange(year, month)[1]
            end_date = datetime(year, month, last_day, 23, 59, 59)

            cursor = await db.execute("""
                SELECT id, title, description, event_date, reminder_minutes, completed
                FROM events
                WHERE event_date BETWEEN ? AND ?
                ORDER BY event_date ASC
            """, (start_date.isoformat(), end_date.isoformat()))
            rows = await cursor.fetchall()

            # Group by day
            events_by_day = {}
            for row in rows:
                event = dict(row)
                event_dt = datetime.fromisoformat(event['event_date'])
                day = event_dt.day
                if day not in events_by_day:
                    events_by_day[day] = []
                events_by_day[day].append(event)

            return events_by_day

    def render_month_calendar(self, year: int, month: int, events_by_day: Dict[int, List[Dict]]) -> str:
        """Render an ASCII calendar for the month with events"""
        cal = pycal.Calendar(firstweekday=6)  # Sunday first
        month_name = pycal.month_name[month]

        # Build calendar
        lines = []
        lines.append(f"╔{'═' * 62}╗")
        lines.append(f"║ {month_name} {year}".ljust(63) + "║")
        lines.append(f"╠{'═' * 62}╣")

        # Day headers
        lines.append("║ Sun    Mon    Tue    Wed    Thu    Fri    Sat          ║")
        lines.append(f"╠{'═' * 62}╣")

        # Get weeks
        weeks = cal.monthdayscalendar(year, month)
        today = datetime.now()

        for week in weeks:
            line = "║"
            for day in week:
                if day == 0:
                    line += "       "
                else:
                    # Check if this is today
                    is_today = (day == today.day and month == today.month and year == today.year)

                    # Check if there are events
                    has_events = day in events_by_day
                    event_count = len(events_by_day.get(day, []))

                    # Format day
                    if is_today and has_events:
                        line += f" [{day:2d}]*  "  # Today with events
                    elif is_today:
                        line += f" [{day:2d}]   "  # Today
                    elif has_events:
                        line += f"  {day:2d}*   "  # Has events
                    else:
                        line += f"  {day:2d}    "  # Regular day

            line += " ║"
            lines.append(line)

        lines.append(f"╚{'═' * 62}╝")
        lines.append("")
        lines.append("Legend: [DD] = Today  | DD* = Has Events | [DD]* = Today + Events")

        return "\n".join(lines)

# Global calendar instance
calendar = Calendar()
