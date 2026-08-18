"""
Unit tests for the four judgment gaps: capability limits, look-before-write,
cross-run learning, and asking instead of guessing.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import capabilities, clarify, lessons
from agent.prechecks import find_existing


class _Backend:
    def __init__(self, reply=None, raises=None):
        self.reply, self.raises = reply, raises

    async def chat(self, messages, **kwargs):
        if self.raises:
            raise self.raises
        return self.reply


# ── #5 capability limits ─────────────────────────────────────────────────────

class TestCapabilities:
    def test_unavailable_capability_names_the_reason(self, monkeypatch):
        """Told only that a tool is missing, the model invents a substitute."""
        monkeypatch.setattr(capabilities, "_CACHE", {})
        monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/nonexistent-home")))
        text = capabilities.describe_for_prompt()
        assert "Google Workspace" in text
        assert "/google-auth" in text

    def test_prompt_forbids_substituting_another_kind_of_tool(self, monkeypatch):
        monkeypatch.setattr(capabilities, "_CACHE", {})
        monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/nonexistent-home")))
        text = capabilities.describe_for_prompt().lower()
        assert "never substitute a different kind of action" in text
        assert "writing a file is not sending an email" in text

    def test_prompt_names_the_working_alternative(self, monkeypatch):
        """
        Regression: told only that calendar_* was unavailable, the planner
        concluded calendar work was impossible and returned an empty plan —
        never noticing nextcloud_* does exactly that job.
        """
        monkeypatch.setattr(capabilities, "_CACHE", {})
        monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/nonexistent-home")))
        text = capabilities.describe_for_prompt()
        assert "nextcloud_" in text
        assert "HOWEVER" in text

    def test_email_has_no_alternative_offered(self, monkeypatch):
        """Substituting a file for an email is exactly what we are preventing."""
        monkeypatch.setattr(capabilities, "_CACHE", {})
        monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/nonexistent-home")))
        assert "no alternative for" in capabilities.describe_for_prompt().lower()

    def test_unavailable_prefixes_cover_the_google_tools(self, monkeypatch):
        monkeypatch.setattr(capabilities, "_CACHE", {})
        monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("/nonexistent-home")))
        assert {"gmail_", "docs_", "sheets_", "calendar_"} <= capabilities.unavailable_prefixes()

    def test_a_broken_probe_does_not_break_planning(self, monkeypatch):
        monkeypatch.setattr(capabilities, "_CACHE", {})
        def boom():
            raise RuntimeError("probe exploded")
        monkeypatch.setitem(capabilities._PROBES, "google", boom)
        caps = capabilities.get_capabilities(force=True)
        assert any("probe exploded" in c.reason for c in caps)


# ── #3 look before you write ─────────────────────────────────────────────────

class TestPrechecks:
    async def test_identical_file_is_reported_as_existing(self, tmp_path, monkeypatch):
        import agent.tools as tools
        monkeypatch.setattr(tools, "_SANDBOX", tmp_path)
        (tmp_path / "note.txt").write_text("SAME")
        found = await find_existing("file_write", {"filename": "note.txt", "content": "SAME"})
        assert found and found.get("already_present")

    async def test_different_content_is_a_legitimate_overwrite(self, tmp_path, monkeypatch):
        import agent.tools as tools
        monkeypatch.setattr(tools, "_SANDBOX", tmp_path)
        (tmp_path / "note.txt").write_text("OLD")
        assert await find_existing("file_write", {"filename": "note.txt", "content": "NEW"}) is None

    async def test_absent_file_has_nothing_to_reuse(self, tmp_path, monkeypatch):
        import agent.tools as tools
        monkeypatch.setattr(tools, "_SANDBOX", tmp_path)
        assert await find_existing("file_write", {"filename": "gone.txt", "content": "X"}) is None

    async def test_tool_without_a_precheck_returns_none(self):
        assert await find_existing("web_search", {"query": "x"}) is None

    async def test_precheck_failure_never_blocks_the_write(self, monkeypatch):
        """Missing a duplicate is far cheaper than refusing to act."""
        async def boom(args):
            raise RuntimeError("calendar unreachable")
        monkeypatch.setitem(__import__("agent.prechecks", fromlist=["PRECHECKS"]).PRECHECKS,
                            "nextcloud_create", boom)
        assert await find_existing("nextcloud_create", {"summary": "x"}) is None


# ── #2 cross-run learning ────────────────────────────────────────────────────

class TestLessons:
    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JRVS_LESSONS_PATH", str(tmp_path / "lessons.json"))
        lessons.clear()

    def test_argument_errors_are_remembered(self):
        lessons.record_tool_error(
            "file_read", "file_read() got unexpected argument(s) ['file_path']"
        )
        assert "file_path" in lessons.format_for_prompt()

    def test_transient_errors_are_not_generalised(self):
        """A network blip is about that moment, not about how to call the tool."""
        lessons.record_tool_error("nextcloud_create", "connection reset by peer")
        assert lessons.format_for_prompt() == ""

    def test_repeats_are_counted_not_duplicated(self):
        for _ in range(3):
            lessons.record_tool_error("file_read", "file_read() got unexpected argument(s) ['x']")
        out = lessons.format_for_prompt()
        assert "seen 3x" in out
        assert out.count("file_read()") == 1

    def test_goal_gaps_are_remembered(self):
        lessons.record_goal_gap("book 6pm", "event is all-day, user asked for 6pm")
        assert "all-day" in lessons.format_for_prompt()

    def test_empty_store_contributes_nothing_to_the_prompt(self):
        assert lessons.format_for_prompt() == ""

    def test_survives_a_corrupt_store(self, tmp_path, monkeypatch):
        path = tmp_path / "broken.json"
        path.write_text("{not json")
        monkeypatch.setenv("JRVS_LESSONS_PATH", str(path))
        assert lessons.format_for_prompt() == ""


# ── #1 ask instead of guess ──────────────────────────────────────────────────

class TestClarify:
    async def test_asks_when_both_conditions_hold(self):
        b = _Backend('{"is_ambiguous": true, "changes_outcome": true,'
                     ' "question": "Is that the title or a separate task?"}')
        ask, q = await clarify.needs_clarification("add an event and make it get groceries", b)
        assert ask and "title" in q

    async def test_ambiguous_but_outcome_unchanged_does_not_ask(self):
        """Both narrow fields must agree — missing detail a default covers is fine."""
        b = _Backend('{"is_ambiguous": true, "changes_outcome": false, "question": "what time?"}')
        ask, _ = await clarify.needs_clarification("book lunch tomorrow", b)
        assert not ask

    async def test_no_question_text_means_no_ask(self):
        b = _Backend('{"is_ambiguous": true, "changes_outcome": true, "question": ""}')
        ask, _ = await clarify.needs_clarification("do the thing properly", b)
        assert not ask

    async def test_very_short_requests_skip_the_gate(self):
        ask, _ = await clarify.needs_clarification("hi", _Backend("unused"))
        assert not ask

    async def test_gate_failure_proceeds_rather_than_blocking(self):
        """A broken screener must never make the assistant unresponsive."""
        b = _Backend(raises=RuntimeError("model offline"))
        ask, _ = await clarify.needs_clarification("some longer request here", b)
        assert not ask

    async def test_unparseable_verdict_proceeds(self):
        ask, _ = await clarify.needs_clarification("some longer request here", _Backend("hmm maybe"))
        assert not ask

    def test_parked_request_round_trips_once(self):
        clarify.park("sess-1", "original request")
        assert clarify.has_pending("sess-1")
        assert clarify.take_pending("sess-1") == "original request"
        assert clarify.take_pending("sess-1") is None   # consumed

    def test_parked_requests_are_per_conversation(self):
        clarify.park("sess-a", "A")
        assert clarify.take_pending("sess-b") is None
        assert clarify.take_pending("sess-a") == "A"

    def test_combine_keeps_both_the_request_and_the_answer(self):
        merged = clarify.combine("book an event, make it get groceries", "it's the title")
        assert "get groceries" in merged and "it's the title" in merged
