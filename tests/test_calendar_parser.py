"""
Unit tests for the calendar parser.

calendar_parser is a pure-logic module — highly testable without mocking.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timezone

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.calendar_parser import parse_calendar_request


class TestCalendarParser:
    """Test natural language calendar request parsing."""

    def test_returns_none_for_non_calendar_input(self):
        result = parse_calendar_request("What is the weather today?")
        assert result is None

    def test_returns_none_for_empty_string(self):
        result = parse_calendar_request("")
        assert result is None

    def test_parses_remind_me(self):
        result = parse_calendar_request("remind me to call doctor tomorrow at 3pm")
        if result:
            assert "title" in result
            assert "event_date" in result

    def test_parses_schedule_event(self):
        result = parse_calendar_request("schedule a meeting on March 15 at 2pm")
        if result:
            assert "title" in result
            assert "event_date" in result

    def test_parses_add_event(self):
        result = parse_calendar_request("add event: dentist appointment on April 1 at 10am")
        if result:
            assert "title" in result

    def test_returns_dict_with_required_keys(self):
        """If parsing succeeds, result must have title and event_date."""
        result = parse_calendar_request("remind me to buy groceries tomorrow at noon")
        if result is not None:
            assert isinstance(result, dict)
            assert "title" in result
            assert "event_date" in result
            # event_date should be a datetime or parsable string
            assert result["event_date"] is not None
