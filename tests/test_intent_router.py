"""
Unit tests for the CLI intent router — pure regex-based command detection.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.intent_router import detect_command_intent, _extract_url


class TestExtractUrl:
    def test_extracts_http(self):
        assert _extract_url("look at http://example.com okay") == "http://example.com"

    def test_extracts_https(self):
        assert _extract_url("scrape https://x.com/page") == "https://x.com/page"

    def test_strips_trailing_punctuation(self):
        assert _extract_url("Visit https://example.com.") == "https://example.com"

    def test_returns_none_for_no_url(self):
        assert _extract_url("no url here") is None


class TestDetectCommandIntent:
    """Tests for the public detect_command_intent function."""

    # ── Should return None ─────────────────────────────────────────────
    def test_short_message_skipped(self):
        assert detect_command_intent("hi") is None

    def test_already_a_command(self):
        assert detect_command_intent("/models") is None

    def test_unrecognised_message(self):
        assert detect_command_intent("Tell me a joke about cats") is None

    # ── Models ─────────────────────────────────────────────────────────
    def test_list_models(self):
        assert detect_command_intent("list all available models") == "/models"

    def test_show_models(self):
        assert detect_command_intent("show me the models") == "/models"

    def test_which_models(self):
        assert detect_command_intent("which models do you have") == "/models"

    # ── Switch model ───────────────────────────────────────────────────
    def test_switch_model(self):
        cmd = detect_command_intent("switch to deepseek-r1:14b")
        assert cmd is not None
        assert cmd.startswith("/switch")
        assert "deepseek" in cmd

    def test_use_model(self):
        cmd = detect_command_intent("use model gemma3:12b please")
        assert cmd is not None
        assert cmd.startswith("/switch")

    # ── Calendar ───────────────────────────────────────────────────────
    def test_calendar_upcoming(self):
        assert detect_command_intent("show me my calendar") == "/calendar"

    def test_upcoming_events(self):
        assert detect_command_intent("what upcoming events do I have") == "/calendar"

    # ── Today ──────────────────────────────────────────────────────────
    def test_todays_events(self):
        assert detect_command_intent("today's events") == "/today"

    def test_what_do_i_have_today(self):
        assert detect_command_intent("what do I have today") == "/today"

    # ── History ────────────────────────────────────────────────────────
    def test_show_chat_history(self):
        assert detect_command_intent("show conversation history") == "/history"

    # ── Stats ──────────────────────────────────────────────────────────
    def test_show_stats(self):
        assert detect_command_intent("show me session stats") == "/stats"

    # ── Sources ────────────────────────────────────────────────────────
    def test_show_sources(self):
        assert detect_command_intent("show sources from last search") == "/sources"

    # ── Scrape ─────────────────────────────────────────────────────────
    def test_scrape_url(self):
        cmd = detect_command_intent("scrape https://example.com/article")
        assert cmd is not None
        assert cmd.startswith("/scrape")
        assert "example.com" in cmd

    # ── Clear ──────────────────────────────────────────────────────────
    def test_clear(self):
        assert detect_command_intent("clear") == "/clear"

    # ── Help ───────────────────────────────────────────────────────────
    def test_help(self):
        assert detect_command_intent("help") == "/help"

    def test_what_can_you_do(self):
        assert detect_command_intent("what can you do") == "/help"

    # ── MCP ────────────────────────────────────────────────────────────
    def test_mcp_servers(self):
        assert detect_command_intent("list mcp servers connected") == "/mcp-servers"

    def test_mcp_tools(self):
        assert detect_command_intent("show mcp tools") == "/mcp-tools"

    # ── Gmail search ───────────────────────────────────────────────────
    def test_gmail_search(self):
        cmd = detect_command_intent("search my emails for invoices")
        assert cmd is not None
        assert cmd.startswith("/gmail search")

    # ── Brave status ───────────────────────────────────────────────────
    def test_brave_status(self):
        assert detect_command_intent("search status remaining") == "/brave-status"
