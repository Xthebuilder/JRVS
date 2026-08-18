"""
Unit tests for post-execution verification.

The failure these guard against: a tool returns a complete, plausible success
payload for work it did not actually do.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.verification import (
    FAILED,
    UNVERIFIED,
    VERIFIED,
    VERIFIERS,
    _same_instant,
    verify_action,
)


class TestSameInstant:
    def test_naive_local_matches_utc_equivalent(self):
        """The planner writes 18:00 local; CalDAV stores 01:00Z next day."""
        import time
        # Only meaningful in a non-UTC zone; skip if the box runs UTC.
        if time.timezone == 0 and not time.daylight:
            pytest.skip("machine is UTC; no offset to test")
        assert _same_instant("2026-08-18T18:00:00", "2026-08-19T01:00:00+00:00")

    def test_different_times_do_not_match(self):
        assert not _same_instant("2026-08-18T18:00:00", "2024-07-18T07:00:00+00:00")

    def test_tolerates_seconds_of_drift(self):
        assert _same_instant("2026-08-18T18:00:00+00:00", "2026-08-18T18:00:30+00:00")

    def test_unparseable_values_do_not_match(self):
        assert not _same_instant("not a date", "2026-08-18T18:00:00+00:00")
        assert not _same_instant(None, None)


class TestVerifyAction:
    async def test_unknown_tool_is_unverified_not_success(self):
        """A tool with no verifier must never be reported as proven."""
        status, detail = await verify_action("some_unmapped_tool", {}, {"ok": True})
        assert status == UNVERIFIED
        assert status != VERIFIED

    async def test_verifier_exception_fails_rather_than_passing(self):
        """
        Regression: the old code returned True whenever a check raised, so a
        broken verifier rubber-stamped every action.
        """
        async def boom(args, result):
            raise RuntimeError("caldav unreachable")

        VERIFIERS["_probe_tool"] = boom
        try:
            status, detail = await verify_action("_probe_tool", {}, {})
            assert status == FAILED
            assert "caldav unreachable" in detail
        finally:
            del VERIFIERS["_probe_tool"]

    async def test_passing_verifier_reports_verified(self):
        async def ok(args, result):
            return True, "read back and matched"

        VERIFIERS["_probe_tool"] = ok
        try:
            status, detail = await verify_action("_probe_tool", {}, {})
            assert status == VERIFIED
            assert detail == "read back and matched"
        finally:
            del VERIFIERS["_probe_tool"]

    async def test_failing_verifier_explains_why(self):
        """Detail feeds the replan, so it must say what was wrong."""
        async def bad(args, result):
            return False, "start is 2024-07-18, expected 2026-08-18"

        VERIFIERS["_probe_tool"] = bad
        try:
            status, detail = await verify_action("_probe_tool", {}, {})
            assert status == FAILED
            assert "2024-07-18" in detail
        finally:
            del VERIFIERS["_probe_tool"]


class TestFileWriteVerifier:
    async def test_missing_file_fails(self, tmp_path, monkeypatch):
        import agent.tools as tools
        monkeypatch.setattr(tools, "_SANDBOX", tmp_path)
        status, detail = await verify_action(
            "file_write", {"filename": "absent.txt", "content": "X"}, {}
        )
        assert status == FAILED
        assert "does not exist" in detail

    async def test_empty_file_fails(self, tmp_path, monkeypatch):
        """A 0-byte file is the silent-no-op signature, not a success."""
        import agent.tools as tools
        monkeypatch.setattr(tools, "_SANDBOX", tmp_path)
        (tmp_path / "empty.txt").write_text("")
        status, detail = await verify_action(
            "file_write", {"filename": "empty.txt", "content": ""}, {}
        )
        assert status == FAILED

    async def test_matching_contents_verify(self, tmp_path, monkeypatch):
        import agent.tools as tools
        monkeypatch.setattr(tools, "_SANDBOX", tmp_path)
        (tmp_path / "ok.txt").write_text("WORKSPACE_OK")
        status, detail = await verify_action(
            "file_write", {"filename": "ok.txt", "content": "WORKSPACE_OK"}, {}
        )
        assert status == VERIFIED

    async def test_contents_differing_from_request_fails(self, tmp_path, monkeypatch):
        import agent.tools as tools
        monkeypatch.setattr(tools, "_SANDBOX", tmp_path)
        (tmp_path / "drift.txt").write_text("SOMETHING ELSE")
        status, detail = await verify_action(
            "file_write", {"filename": "drift.txt", "content": "WORKSPACE_OK"}, {}
        )
        assert status == FAILED


class TestNextcloudCreateVerifier:
    async def test_missing_event_id_fails(self):
        status, detail = await verify_action(
            "nextcloud_create", {"summary": "x", "start": "2026-08-18T18:00:00"}, {}
        )
        assert status == FAILED
        assert "no event id" in detail
