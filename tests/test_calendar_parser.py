"""
Unit tests for the calendar parser.

calendar_parser is a pure-logic module — highly testable without mocking.
"""

import sys
from pathlib import Path
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.calendar_parser import (
    parse_calendar_request,
    build_calendar_grounding,
    format_event_confirmation,
    looks_calendar_related,
    DEFAULT_HOUR,
)


class TestCalendarParser:
    """Test natural language calendar request parsing."""

    def test_returns_none_for_non_calendar_input(self):
        assert parse_calendar_request("What is the weather today?") is None

    def test_returns_none_for_empty_string(self):
        assert parse_calendar_request("") is None

    def test_parses_remind_me(self):
        result = parse_calendar_request("remind me to call doctor tomorrow at 3pm")
        assert result is not None
        assert result["title"] == "Call doctor"
        assert result["event_date"].hour == 15
        assert result["time_explicit"] is True

    def test_parses_schedule_event(self):
        result = parse_calendar_request("schedule a meeting on friday at 2pm")
        assert result is not None
        assert result["title"] == "Meeting"
        assert result["event_date"].hour == 14

    def test_parses_add_event(self):
        result = parse_calendar_request("add event: dentist appointment tomorrow at 10am")
        assert result is not None
        assert result["title"] == "Dentist appointment"

    def test_returns_dict_with_required_keys(self):
        result = parse_calendar_request("remind me to buy groceries tomorrow at noon")
        assert isinstance(result, dict)
        assert set(result) >= {"title", "event_date", "date_explicit", "time_explicit"}
        assert isinstance(result["event_date"], datetime)


class TestTimeIsOptional:
    """The original parser required a time and silently dropped anything without
    one — the bug that made JRVS claim it had created an event it never made."""

    def test_request_without_time_still_parses(self):
        result = parse_calendar_request(
            "can you set calandar event for today , interview with job site ?"
        )
        assert result is not None
        assert result["title"] == "Interview with job site"
        assert result["date_explicit"] is True
        assert result["time_explicit"] is False
        assert result["event_date"].hour == DEFAULT_HOUR

    def test_misspelled_calendar_still_parses(self):
        assert parse_calendar_request("add a calender event tomorrow, standup") is not None

    def test_assumed_time_is_flagged(self):
        result = parse_calendar_request("add a meeting with sarah next tuesday")
        assert result["time_explicit"] is False
        assert result["date_explicit"] is True

    def test_bare_number_is_not_a_time(self):
        """The old regex matched any 1-2 digits anywhere, so an ISO date's year
        supplied the hour."""
        result = parse_calendar_request("set a calendar event 2026-08-12 interview with job site")
        assert result is not None
        assert result["event_date"].date() == datetime(2026, 8, 12).date()
        assert result["time_explicit"] is False
        assert result["event_date"].hour == DEFAULT_HOUR

    def test_no_date_defaults_to_today_not_tomorrow(self):
        result = parse_calendar_request("add a meeting at 11:59 pm")
        assert result["date_explicit"] is False
        assert result["event_date"].date() == datetime.now().date()

    def test_assumed_datetime_never_lands_in_the_past(self):
        result = parse_calendar_request("add a meeting about budget")
        assert result["event_date"] >= datetime.now()


class TestIntentGate:
    """Time being optional widens the net, so the intent gate has to be tight."""

    @pytest.mark.parametrize("msg", [
        "set the volume to 70",
        "set the thermostat to 72 degrees",
        "create a new file",
        "add pandas to requirements",
    ])
    def test_create_verb_without_event_noun_is_ignored(self, msg):
        assert parse_calendar_request(msg) is None

    @pytest.mark.parametrize("msg", [
        "werer you able to add the event ?",
        "were you able to add the event?",
        "did you add the event?",
        "was the meeting scheduled?",
        "can we confirm the event was added?",
        "have you created that appointment yet?",
    ])
    def test_questions_about_events_do_not_create_events(self, msg):
        """A user following up on a failed request must not silently create a
        duplicate."""
        assert parse_calendar_request(msg) is None

    @pytest.mark.parametrize("msg", [
        "whats on my calendar today",
        "show me my meetings",
    ])
    def test_read_requests_do_not_create_events(self, msg):
        assert parse_calendar_request(msg) is None


class TestGrounding:
    """The model can't see whether add_event() ran, so it must be told."""

    def test_positive_grounding_names_the_event(self):
        parsed = parse_calendar_request("add a meeting tomorrow at 2pm about budget")
        note = build_calendar_grounding("add a meeting tomorrow at 2pm about budget", parsed, 42)
        assert "WAS created" in note
        assert "#42" in note
        assert parsed["title"] in note

    def test_positive_grounding_discloses_assumptions(self):
        parsed = parse_calendar_request("add a calendar event tomorrow, interview")
        note = build_calendar_grounding("add a calendar event tomorrow, interview", parsed, 7)
        assert "assumed the time" in note

    def test_failed_parse_gets_explicit_denial(self):
        msg = "were you able to add the event?"
        assert parse_calendar_request(msg) is None
        note = build_calendar_grounding(msg, None, None)
        assert "No calendar event was created" in note
        assert "Do not claim" in note

    def test_unrelated_message_gets_no_grounding(self):
        assert build_calendar_grounding("what is the weather?", None, None) == ""

    def test_confirmation_line_includes_id_and_time(self):
        parsed = parse_calendar_request("add a meeting tomorrow at 2pm about budget")
        line = format_event_confirmation(parsed, 99)
        assert "#99" in line
        assert "02:00 PM" in line

    def test_looks_calendar_related(self):
        assert looks_calendar_related("did you add the event?") is True
        assert looks_calendar_related("what is the weather?") is False
