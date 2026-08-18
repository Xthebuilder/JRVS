"""
Shared natural-language calendar parser used by both the CLI and the API server.

parse_calendar_request(message) -> Optional[Dict]

Returns None if the message doesn't look like a *request to create* an event,
otherwise:
  {
    "title":         str,
    "event_date":    datetime,
    "date_explicit": bool,   # False => we assumed the date
    "time_explicit": bool,   # False => we assumed the time
  }

Design notes
------------
* Time is optional. A message like "set a calendar event for today, interview
  with job site" is a valid request; we default to DEFAULT_HOUR and report
  time_explicit=False so callers can tell the user what was assumed.
* The intent gate requires a create-verb AND an event-noun (or "remind me").
  A bare keyword match is far too loose once time is optional -- "set the
  volume to 70" must not create an event.
* Past-tense questions ("did you add the event?", "were you able to schedule
  it?") are explicitly rejected. They contain create-verbs and event-nouns but
  are asking *about* an event, not asking for one. Without this guard, a user
  following up on a failed request would silently create a duplicate.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

# Hour used when the user names a date but no time.
DEFAULT_HOUR = 9

# Verbs that signal "make me one of these"
_CREATE_VERBS = r"(?:add|create|schedule|set|book|put|make|new)"

# Nouns that signal the thing being made is a calendar entry.
# Common misspellings included deliberately -- they show up constantly in
# voice transcription and fast typing.
_EVENT_NOUNS = r"(?:calendar|calandar|calender|event|meeting|appointment|reminder)"

# Day-name -> weekday index (Monday=0)
_DAY_NAMES = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
}

_CREATE_VERB_RE = re.compile(rf"\b{_CREATE_VERBS}\b", re.IGNORECASE)
_EVENT_NOUN_RE = re.compile(rf"\b{_EVENT_NOUNS}s?\b", re.IGNORECASE)
_REMIND_ME_RE = re.compile(r"\bremind\s+me\b", re.IGNORECASE)

# Questions *about* an event rather than requests *for* one.
_PAST_TENSE_RE = re.compile(
    # Yes/no question openers. A message *starting* with one of these is asking
    # about state, never requesting an action ("can/could/would you" are
    # requests and are deliberately absent).
    r"^\s*(?:did|were|was|have|has|had|is|are|do|does|didn'?t|weren'?t)\b"
    r"|\b(?:did|were|was|have|has|had|didn'?t|weren'?t|couldn'?t)\s+"
    r"(?:you|u|it|we|jrvs|jarvis)\b"
    # "able to <verb>" catches capability questions without depending on the
    # spelling of the auxiliary -- "werer you able to add the event?" is a real
    # thing users type, and must not create an event.
    r"|\bable\s+to\b"
    r"|\b(?:you|it)\s+(?:already\s+)?(?:added|created|scheduled|booked|made)\b"
    r"|\b(?:can|could)\s+(?:we|you|i)\s+(?:confirm|check|verify|see)\b",
    re.IGNORECASE,
)


def _parse_time(msg: str) -> Optional[Tuple[int, int, str]]:
    """
    Find an explicit time. Returns (hour, minute, matched_text) or None.

    Only explicit time forms count -- a bare number is not a time. The old
    regex matched any 1-2 digits anywhere, so "add event 2026-08-12" parsed
    the "20" out of the year and produced an 8pm event.
    """
    # 3:30, 3:30pm, 15:00
    m = re.search(r"\b(?:at\s+)?(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?\b", msg, re.IGNORECASE)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        meridiem = (m.group(3) or "").lower().replace(".", "")
        hour = _apply_meridiem(hour, meridiem)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute, m.group(0)

    # 3pm, 3 pm  (meridiem required -- "at 3" is too ambiguous to act on)
    m = re.search(r"\b(?:at\s+)?(\d{1,2})\s*([ap]\.?m\.?)\b", msg, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        meridiem = m.group(2).lower().replace(".", "")
        hour = _apply_meridiem(hour, meridiem)
        if 0 <= hour <= 23:
            return hour, 0, m.group(0)

    m = re.search(r"\b(noon|midday)\b", msg, re.IGNORECASE)
    if m:
        return 12, 0, m.group(0)

    m = re.search(r"\bmidnight\b", msg, re.IGNORECASE)
    if m:
        return 0, 0, m.group(0)

    return None


def _apply_meridiem(hour: int, meridiem: str) -> int:
    if meridiem == "pm" and hour != 12:
        return hour + 12
    if meridiem == "am" and hour == 12:
        return 0
    # No meridiem given: 1-6 o'clock almost certainly means afternoon/evening.
    if not meridiem and 1 <= hour <= 6:
        return hour + 12
    return hour


def _parse_date(msg_lower: str) -> Tuple[Optional[datetime], Optional[str]]:
    """Find a date. Returns (date, matched_text) -- both None if not found."""
    iso = re.search(r"\d{4}-\d{1,2}-\d{1,2}", msg_lower)
    if iso:
        try:
            return datetime.strptime(iso.group(0), "%Y-%m-%d"), iso.group(0)
        except ValueError:
            pass

    if "day after tomorrow" in msg_lower:
        return datetime.now() + timedelta(days=2), "day after tomorrow"
    if "tomorrow" in msg_lower:
        return datetime.now() + timedelta(days=1), "tomorrow"
    if "tonight" in msg_lower:
        return datetime.now(), "tonight"
    if "today" in msg_lower:
        return datetime.now(), "today"
    if "next week" in msg_lower:
        return datetime.now() + timedelta(days=7), "next week"

    for day_name, weekday_idx in _DAY_NAMES.items():
        m = re.search(rf"\b(?:this\s+|next\s+)?{day_name}\b", msg_lower)
        if m:
            today = datetime.now()
            days_ahead = weekday_idx - today.weekday()
            if days_ahead <= 0 or m.group(0).startswith("next"):
                days_ahead += 7
            return today + timedelta(days=days_ahead), m.group(0)

    return None, None


def _extract_title(message: str, time_text: Optional[str], date_text: Optional[str]) -> str:
    """Strip the scaffolding off the request, leaving the subject."""
    title = message

    # Leading politeness / addressing
    title = re.sub(r"^\s*(?:hey|hi|ok|okay|yo)\b[,\s]*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^\s*(?:jrvs|jarvis)\b[,:\s]*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^\s*(?:can|could|would|will)\s+(?:you|u)\s+(?:please\s+)?", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^\s*(?:please|pls|plz)\s+", "", title, flags=re.IGNORECASE)

    # Leading create verb + article
    # \b after the article group matters: without it "book an appointment"
    # matches the "a" of "an" and leaves a stray "n".
    title = re.sub(
        rf"^\s*{_CREATE_VERBS}\s+(?:up\s+)?(?:\b(?:an|a|the|new|my|me)\b\s*)?",
        "", title, flags=re.IGNORECASE,
    )
    title = re.sub(r"^\s*remind\s+me\s+(?:to\s+|about\s+)?", "", title, flags=re.IGNORECASE)

    # The date/time expressions we already consumed
    for consumed in (time_text, date_text):
        if consumed:
            title = re.sub(rf"(?:\bat\s+)?{re.escape(consumed)}", " ", title, flags=re.IGNORECASE)

    # Leading filler: "calendar event for", "an appointment on", ...
    filler = r"(?:calendar|calandar|calender|events?|entry|for|on|at|to|in|of|an|a|the|my|our|new|up|about)"
    title = re.sub(rf"^(?:\s*{filler}\b)+", "", title, flags=re.IGNORECASE)
    # Trailing prepositions stranded by removing the date/time they governed
    # ("meeting on <friday>" -> "meeting on").
    title = re.sub(r"(?:\s*\b(?:for|on|at|to|in|of|with|about)\b\s*[,.]?)+\s*$", "", title, flags=re.IGNORECASE)

    title = re.sub(r"\s+", " ", title).strip(" ,.;:-?!—")

    if len(title) < 3:
        msg_lower = message.lower()
        if "interview" in msg_lower:
            title = "Interview"
        elif "meeting" in msg_lower:
            with_match = re.search(r"with\s+(.+?)(?:\s+at\b|\s+on\b|$)", msg_lower)
            title = f"Meeting w/ {with_match.group(1).title()}" if with_match else "Meeting"
        elif "appointment" in msg_lower:
            title = "Appointment"
        elif "reminder" in msg_lower or "remind" in msg_lower:
            title = "Reminder"
        else:
            title = "Event"
    else:
        title = title[0].upper() + title[1:]

    if len(title) > 50:
        title = title[:47] + "..."

    return title


def looks_calendar_related(message: str) -> bool:
    """
    True if the message is *about* calendar entries at all -- including
    questions and failed requests. Callers use this to decide whether the model
    needs to be told that no event was created.
    """
    return bool(_EVENT_NOUN_RE.search(message) or _REMIND_ME_RE.search(message))


def has_create_intent(message: str) -> bool:
    """True if the message asks for an event to be created."""
    if _PAST_TENSE_RE.search(message):
        return False
    if _REMIND_ME_RE.search(message):
        return True
    return bool(_CREATE_VERB_RE.search(message) and _EVENT_NOUN_RE.search(message))


def parse_calendar_request(message: str) -> Optional[Dict]:
    """
    Try to extract a calendar event from a natural-language message.
    Returns a dict with title/event_date/date_explicit/time_explicit, or None.
    """
    if not message or not has_create_intent(message):
        return None

    msg_lower = message.lower()

    parsed_time = _parse_time(msg_lower)
    time_explicit = parsed_time is not None
    hour, minute, time_text = parsed_time if parsed_time else (DEFAULT_HOUR, 0, None)

    event_date, date_text = _parse_date(msg_lower)
    date_explicit = event_date is not None
    if event_date is None:
        event_date = datetime.now()

    event_date = event_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Never land in the past on assumptions alone. If the user was explicit
    # about the day, respect it -- they may be backfilling.
    if not date_explicit and event_date < datetime.now():
        event_date += timedelta(days=1)

    return {
        "title": _extract_title(message, time_text, date_text),
        "event_date": event_date,
        "date_explicit": date_explicit,
        "time_explicit": time_explicit,
    }


def describe_assumptions(parsed: Dict) -> str:
    """Human-readable note about what we guessed, or '' if nothing was guessed."""
    missing = []
    if not parsed.get("date_explicit"):
        missing.append("date")
    if not parsed.get("time_explicit"):
        missing.append("time")
    if not missing:
        return ""
    return (
        f"assumed the {' and '.join(missing)} "
        f"({parsed['event_date'].strftime('%A, %B %d at %I:%M %p')})"
    )


def format_event_confirmation(parsed: Dict, event_id: int) -> str:
    """Deterministic one-line confirmation shown to the user regardless of what
    the model says. Includes anything we had to guess."""
    line = (
        f"✓ Created event #{event_id}: \"{parsed['title']}\" — "
        f"{parsed['event_date'].strftime('%A, %B %d, %Y at %I:%M %p')}"
    )
    assumptions = describe_assumptions(parsed)
    if assumptions:
        line += f"\n  (I {assumptions} — tell me if you want it changed.)"
    return line


def build_calendar_grounding(message: str, parsed: Optional[Dict], event_id: Optional[int]) -> str:
    """
    Ground-truth note about what the calendar tool actually did, to be appended
    to the model's context.

    The model cannot see whether add_event() ran. Left to guess, it will happily
    invent a confirmation -- which is exactly what it did before this existed.
    Returns '' when the message has nothing to do with the calendar.
    """
    if parsed and event_id:
        note = (
            f"A calendar event WAS created: #{event_id}, titled "
            f"\"{parsed['title']}\", for "
            f"{parsed['event_date'].strftime('%A, %B %d, %Y at %I:%M %p')}. "
            f"Confirm this to the user using exactly this title, date and time."
        )
        assumptions = describe_assumptions(parsed)
        if assumptions:
            note += (
                f" You {assumptions} because the user did not specify it -- "
                f"say so plainly and offer to change it."
            )
        return f"[CALENDAR TOOL RESULT] {note}"

    if looks_calendar_related(message):
        return (
            "[CALENDAR TOOL RESULT] No calendar event was created and no calendar "
            "was read. You have NO working calendar tool in this turn. Do not claim "
            "that you added, scheduled, checked, or confirmed anything. If the user "
            "asked for an event, tell them plainly it was not created and ask for "
            "the date and time."
        )

    return ""
