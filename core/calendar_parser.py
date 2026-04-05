"""
Shared natural-language calendar parser used by both the CLI and the API server.

parse_calendar_request(message) -> Optional[Dict]

Returns None if the message doesn't look like a calendar request, otherwise:
  {
    "title":      str,
    "event_date": datetime,
  }
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Dict

# Keywords that suggest a calendar intent
_CALENDAR_KEYWORDS = {
    'add', 'create', 'schedule', 'set', 'calendar', 'event',
    'meeting', 'reminder', 'appointment', 'remind', 'book',
}

# Day-name → weekday index (Monday=0)
_DAY_NAMES = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
}


def parse_calendar_request(message: str) -> Optional[Dict]:
    """
    Try to extract a calendar event from a natural-language message.
    Returns a dict with 'title' and 'event_date', or None if no event detected.
    """
    msg_lower = message.lower()

    # ── Require at least one calendar keyword ────────────────────────────────
    if not any(kw in msg_lower for kw in _CALENDAR_KEYWORDS):
        return None

    # ── Parse time ───────────────────────────────────────────────────────────
    time_match = re.search(
        r'(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?',
        msg_lower
    )
    if not time_match:
        return None

    hour   = int(time_match.group(1))
    minute = int(time_match.group(2)) if time_match.group(2) else 0
    meridiem = time_match.group(3)

    if meridiem == 'pm' and hour != 12:
        hour += 12
    elif meridiem == 'am' and hour == 12:
        hour = 0

    # ── Parse date ───────────────────────────────────────────────────────────
    event_date: Optional[datetime] = None

    # Explicit ISO date: 2025-11-15
    iso_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', msg_lower)
    if iso_match:
        event_date = datetime.strptime(iso_match.group(1), "%Y-%m-%d")

    elif 'tomorrow' in msg_lower:
        event_date = datetime.now() + timedelta(days=1)

    elif 'today' in msg_lower:
        event_date = datetime.now()

    elif 'next week' in msg_lower:
        event_date = datetime.now() + timedelta(days=7)

    else:
        # Named weekday: "this Monday", "next Friday", bare "Tuesday" etc.
        for day_name, weekday_idx in _DAY_NAMES.items():
            if day_name in msg_lower:
                today = datetime.now()
                days_ahead = weekday_idx - today.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                event_date = today + timedelta(days=days_ahead)
                break

    if event_date is None:
        event_date = datetime.now() + timedelta(days=1)   # default: tomorrow

    event_date = event_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # ── Extract title ────────────────────────────────────────────────────────
    title = message

    # Strip common leading verbs/phrases
    for prefix in [
        'add calendar event', 'add event', 'create calendar event', 'create event',
        'schedule a', 'schedule an', 'schedule', 'set a', 'set an',
        'add a', 'add an', 'add', 'remind me to', 'remind me',
    ]:
        if msg_lower.startswith(prefix):
            title = title[len(prefix):].strip()
            break

    # Strip time expression
    title = re.sub(r'(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?', '', title,
                   flags=re.IGNORECASE).strip()

    # Strip date references
    for token in ['tomorrow', 'today', 'next week']:
        title = re.sub(rf'\b{token}\b', '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r'\d{4}-\d{1,2}-\d{1,2}', '', title).strip()
    for day_name in _DAY_NAMES:
        title = re.sub(
            rf'\b(?:this|next)?\s*{day_name}\b', '', title, flags=re.IGNORECASE
        ).strip()
    title = re.sub(r'\bto\s+jrvs\b', '', title, flags=re.IGNORECASE).strip()

    # Clean up whitespace and punctuation
    title = re.sub(r'\s+', ' ', title).strip(' ,.-')

    # Smart fallback title
    if not title or len(title) < 3:
        if 'meeting' in msg_lower:
            with_match = re.search(
                r'with\s+(.+?)(?:\s+at|\s+tomorrow|\s+today|$)', msg_lower
            )
            title = f"Meeting w/ {with_match.group(1).title()}" if with_match else "Meeting"
        elif 'appointment' in msg_lower:
            title = "Appointment"
        elif 'reminder' in msg_lower:
            title = "Reminder"
        else:
            title = "Event"

    if len(title) > 50:
        title = title[:47] + "..."

    return {"title": title, "event_date": event_date}
