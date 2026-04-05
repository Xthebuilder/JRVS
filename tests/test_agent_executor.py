"""
Unit tests for the agent executor — tier enforcement, arg resolution, dispatch.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from jrvs.agent.executor import (
    AUTO, NOTIFY, CONFIRM, BLOCKED,
    TIER_MAP, Executor, _max_tier, _resolve_args, _truncate,
)


class TestTierMap:
    """Verify the tier configuration is consistent."""

    def test_all_tiers_valid(self):
        valid = {AUTO, NOTIFY, CONFIRM, BLOCKED}
        for tool, tier in TIER_MAP.items():
            assert tier in valid, f"Tool '{tool}' has invalid tier '{tier}'"

    def test_read_tools_are_auto(self):
        read_tools = ["gmail_list", "gmail_search", "gmail_read",
                      "docs_list", "docs_read", "sheets_list", "sheets_read",
                      "calendar_events"]
        for tool in read_tools:
            assert TIER_MAP[tool] == AUTO, f"{tool} should be AUTO"

    def test_write_tools_are_notify(self):
        write_tools = ["docs_create", "docs_append", "sheets_write",
                       "calendar_create", "calendar_update"]
        for tool in write_tools:
            assert TIER_MAP[tool] == NOTIFY, f"{tool} should be NOTIFY"

    def test_destructive_tools_are_confirm(self):
        assert TIER_MAP["gmail_send"] == CONFIRM
        assert TIER_MAP["gmail_reply"] == CONFIRM
        assert TIER_MAP["calendar_delete"] == CONFIRM


class TestMaxTier:
    def test_auto_vs_auto(self):
        assert _max_tier(AUTO, AUTO) == AUTO

    def test_auto_vs_confirm(self):
        assert _max_tier(AUTO, CONFIRM) == CONFIRM

    def test_notify_vs_blocked(self):
        assert _max_tier(NOTIFY, BLOCKED) == BLOCKED

    def test_confirm_vs_notify(self):
        assert _max_tier(CONFIRM, NOTIFY) == CONFIRM


class TestResolveArgs:
    def test_no_placeholders(self):
        args = {"query": "hello", "count": 5}
        result = _resolve_args(args, {})
        assert result == args

    def test_resolves_step_reference(self):
        args = {"data": "<result_from_step_1>"}
        step_results = {1: {"emails": ["a@b.com"]}}
        result = _resolve_args(args, step_results)
        assert result["data"] == {"emails": ["a@b.com"]}

    def test_unresolved_placeholder_kept(self):
        args = {"data": "<result_from_step_99>"}
        step_results = {1: "something"}
        result = _resolve_args(args, step_results)
        assert result["data"] == "<result_from_step_99>"

    def test_non_string_values_untouched(self):
        args = {"count": 42, "flag": True}
        result = _resolve_args(args, {1: "x"})
        assert result["count"] == 42
        assert result["flag"] is True


class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_string_truncated(self):
        result = _truncate("a" * 200, 50)
        assert len(result) == 51  # 50 + ellipsis char
        assert result.endswith("…")


class TestExecutorDryRun:
    """Test executor in dry_run mode so nothing actually dispatches."""

    def setup_method(self):
        self.mock_db = MagicMock()
        self.executor = Executor(db=self.mock_db, dry_run=True)

    def test_dry_run_returns_dry_run_status(self):
        step = {"step": 1, "tool": "gmail_list", "args": {}, "reason": "test"}
        result = self.executor.execute_step(step, run_id="test-run")
        assert result["status"] == "dry_run"

    def test_blocked_tool_stays_blocked_even_in_dry_run(self):
        # Add a tool as blocked
        step = {"step": 1, "tool": "unknown_destructive", "args": {}, "reason": "test"}
        # unknown tool defaults to CONFIRM, but let's test a real blocked one
        # by patching TIER_MAP
        with patch.dict(TIER_MAP, {"fake_tool": BLOCKED}):
            step["tool"] = "fake_tool"
            result = self.executor.execute_step(step, run_id="test-run")
            assert result["status"] == "blocked"

    def test_confirm_tier_queues_for_approval(self):
        # Not in dry_run for this test
        executor = Executor(db=self.mock_db, dry_run=False)
        step = {"step": 1, "tool": "gmail_send", "args": {"to": "test@test.com"},
                "reason": "test"}
        result = executor.execute_step(step, run_id="test-run")
        assert result["status"] == "awaiting_approval"
