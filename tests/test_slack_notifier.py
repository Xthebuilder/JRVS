"""
Unit tests for the Slack channel router — pure keyword scoring, no network.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.slack_notifier import _confidence_route, get_channel, CHANNEL_KEYS


@pytest.fixture(autouse=True)
def _pin_threshold(monkeypatch):
    """Pin the threshold so tests don't depend on the developer's .env."""
    monkeypatch.setenv("SLACK_ROUTE_CONFIDENCE", "0.65")


class TestConfidenceRoute:
    """Routing of realistic JARVIS notification text."""

    @pytest.mark.parametrize(
        "expected, text",
        [
            ("inbox", "New email from Bob Chen — subject: Q3 budget approval"),
            ("inbox", "You have 3 unread emails in your inbox"),
            ("inbox", "Draft reply ready for review"),
            ("calendar", "Your daily brief: 2 meetings scheduled today"),
            ("calendar", "Calendar conflict: two events overlap tomorrow at 2pm"),
            ("calendar", "End of day summary ready"),
            ("research", "Weekly research report on AI tools trends is ready"),
            ("research", "Web search finished — 12 articles found"),
            ("schedule", "Scheduled job completed. Next run at 6am"),
            ("schedule", "Cron task ran successfully"),
            ("alerts", "Error: gmail_send failed with a timeout"),
            ("alerts", "Unauthorized — token expired, traceback follows"),
        ],
    )
    def test_routes_to_expected_channel(self, expected, text):
        channel, confidence = _confidence_route(text)
        assert channel == expected
        assert confidence >= 0.65

    @pytest.mark.parametrize(
        "text",
        [
            "Hey, just checking in",
            "Done.",
            "Here is the thing you asked about",
        ],
    )
    def test_unremarkable_text_falls_back_to_general(self, text):
        channel, confidence = _confidence_route(text)
        assert channel == "general"
        assert confidence < 0.65

    def test_no_keyword_hits_scores_zero(self):
        assert _confidence_route("qwerty zxcvbn") == ("general", 0.0)


class TestRoutingGuards:
    """The two failure modes the scoring is specifically shaped to avoid."""

    def test_realistic_message_is_not_starved_by_vocabulary_size(self):
        """
        Regression: confidence was hits/len(keywords), i.e. the fraction of a
        channel's whole vocabulary present. With ~12 keywords per channel and a
        0.65 threshold that required 8 distinct keywords in one message, so
        every realistic notification fell through to 'general'.
        """
        channel, _ = _confidence_route("You have 3 unread emails in your inbox")
        assert channel == "inbox"

    def test_single_ambiguous_word_does_not_win_a_channel(self):
        """One common word is not enough evidence on its own."""
        for text in ("the email arrived", "gmail is down", "blocked by firewall"):
            channel, confidence = _confidence_route(text)
            assert channel == "general", f"{text!r} routed to {channel}"
            assert confidence < 0.65

    def test_keywords_match_on_word_boundaries(self):
        """'mail' must not match inside 'gmail'/'email' and inflate the score."""
        bare, _ = _confidence_route("gmail is down")
        assert bare == "general"

    def test_plurals_still_match(self):
        """Leading-only boundary means 'meeting' matches 'meetings'."""
        channel, _ = _confidence_route("Two meetings on the calendar tomorrow")
        assert channel == "calendar"

    def test_multiword_phrase_counts_as_strong_evidence(self):
        """A specific phrase should route on its own; a bare word should not."""
        phrase, phrase_conf = _confidence_route("End of day summary ready")
        assert phrase == "calendar"

        word, word_conf = _confidence_route("ready today")
        assert word_conf < phrase_conf

    def test_contested_message_prefers_the_dominant_channel(self):
        """More independent evidence wins over a single incidental hit."""
        channel, _ = _confidence_route(
            "Error: the scheduled job failed with a traceback and timeout"
        )
        assert channel == "alerts"


class TestGetChannel:
    def test_known_key_reads_its_env_var(self, monkeypatch):
        monkeypatch.setenv("SLACK_CHANNEL_INBOX", "#custom-inbox")
        assert get_channel("inbox") == "#custom-inbox"

    def test_unknown_key_falls_back_to_general(self, monkeypatch):
        monkeypatch.setenv("SLACK_CHANNEL_GENERAL", "#fallback")
        assert get_channel("nonsense") == "#fallback"

    def test_every_channel_key_has_a_default(self, monkeypatch):
        for key in CHANNEL_KEYS:
            monkeypatch.delenv(CHANNEL_KEYS[key], raising=False)
            assert get_channel(key).startswith("#")
