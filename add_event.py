#!/usr/bin/env python3
"""Quick script to add calendar events to JRVS"""
import asyncio
import aiosqlite
from datetime import datetime
import sys

async def add_event(title: str, date_str: str, time_str: str = "09:00", description: str = ""):
    """Add event to JRVS calendar

    Args:
        title: Event title
        date_str: Date in format YYYY-MM-DD
        time_str: Time in format HH:MM (default: 09:00)
        description: Optional event description
    """
    db_path = 'data/jarvis.db'

    # Parse datetime
    dt_str = f"{date_str} {time_str}"
    event_date = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute('''
            INSERT INTO events (title, description, event_date, reminder_minutes, completed)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, description, event_date.isoformat(), 0, False))
        await db.commit()
        event_id = cursor.lastrowid
        print(f"✓ Event added (ID: {event_id})")
        print(f"  Title: {title}")
        print(f"  Date: {event_date.strftime('%Y-%m-%d %H:%M')}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python add_event.py <title> <date> [time] [description]")
        print("Example: python add_event.py 'Team meeting' 2025-11-15 14:30 'Discuss project'")
        sys.exit(1)

    title = sys.argv[1]
    date = sys.argv[2]
    time = sys.argv[3] if len(sys.argv) > 3 else "09:00"
    desc = sys.argv[4] if len(sys.argv) > 4 else ""

    asyncio.run(add_event(title, date, time, desc))
