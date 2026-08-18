"""
Unit tests for the goal-satisfaction gate (the outer loop).

Per-step verification proves a tool did what it was TOLD. This gate asks the
other question — did the user get what they ASKED for — so its job is to fail
a plan that ran perfectly against the wrong intent.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.goal_check import (
    GAP,
    INDETERMINATE,
    SATISFIED,
    _parse_verdict,
    check_goal_satisfied,
    format_evidence,
)


class _Step:
    def __init__(self, step, tool, args):
        self.step, self.tool, self.args = step, tool, args


class _Backend:
    """Stub LLM returning a canned verdict, or raising."""
    def __init__(self, reply=None, raises=None):
        self.reply, self.raises = reply, raises
        self.last_messages = None

    async def chat(self, messages, **kwargs):
        if self.raises:
            raise self.raises
        self.last_messages = messages
        return self.reply


class TestParseVerdict:
    def test_plain_json(self):
        assert _parse_verdict('{"action_performed": true}') == {"action_performed": True}

    def test_fenced_json(self):
        out = _parse_verdict('```json\n{"matches_request": false}\n```')
        assert out == {"matches_request": False}

    def test_json_with_surrounding_prose(self):
        out = _parse_verdict('Sure!\n{"action_performed": true}\nHope that helps')
        assert out == {"action_performed": True}

    def test_unparseable_returns_none(self):
        assert _parse_verdict("no json here") is None
        assert _parse_verdict("") is None


class TestFormatEvidence:
    def test_includes_tool_args_and_verification(self):
        plan = [_Step(1, "nextcloud_create", {"summary": "Lunch", "start": "2026-08-18"})]
        outcomes = {1: {"status": "success", "verification": "verified"}}
        text = format_evidence(outcomes, plan)
        assert "nextcloud_create" in text
        assert "Lunch" in text
        assert "verified" in text

    def test_no_steps_is_stated_explicitly(self):
        assert "no steps ran" in format_evidence({}, [])

    def test_unverified_status_is_surfaced(self):
        """The auditor must be able to see that nothing was confirmed."""
        plan = [_Step(1, "nextcloud_find", {"query": "x"})]
        outcomes = {1: {"status": "success", "verification": "unverified"}}
        assert "unverified" in format_evidence(outcomes, plan)


class TestCheckGoalSatisfied:
    async def test_both_booleans_true_is_satisfied(self):
        b = _Backend('{"action_performed": true, "matches_request": true, "missing": ""}')
        status, missing = await check_goal_satisfied("book 6pm", "evidence", b)
        assert status == SATISFIED
        assert missing == ""

    async def test_action_performed_but_details_wrong_is_a_gap(self):
        """The all-day-vs-6pm case: it ran, it just isn't what was asked."""
        b = _Backend(
            '{"action_performed": true, "matches_request": false,'
            ' "missing": "event is all-day, user asked for 6pm"}'
        )
        status, missing = await check_goal_satisfied("book 6pm", "evidence", b)
        assert status == GAP
        assert "6pm" in missing

    async def test_nothing_performed_is_a_gap(self):
        b = _Backend('{"action_performed": false, "matches_request": false, "missing": ""}')
        status, missing = await check_goal_satisfied("book 6pm", "evidence", b)
        assert status == GAP
        assert missing  # always explains itself, even when the model gives nothing

    async def test_one_true_one_false_never_passes(self):
        """Both narrow fields must agree — this is why it is not one score."""
        b = _Backend('{"action_performed": true, "matches_request": false, "missing": ""}')
        status, _ = await check_goal_satisfied("x", "y", b)
        assert status != SATISFIED

    async def test_unparseable_verdict_is_not_success(self):
        b = _Backend("the assistant did great!")
        status, missing = await check_goal_satisfied("x", "y", b)
        assert status == INDETERMINATE
        assert status != SATISFIED

    async def test_audit_failure_is_not_success(self):
        """A broken auditor must never be read as approval."""
        b = _Backend(raises=RuntimeError("model offline"))
        status, missing = await check_goal_satisfied("x", "y", b)
        assert status == INDETERMINATE
        assert "model offline" in missing

    async def test_request_and_evidence_both_reach_the_auditor(self):
        b = _Backend('{"action_performed": true, "matches_request": true}')
        await check_goal_satisfied("book dinner at 6pm", "ran nextcloud_create", b)
        sent = b.last_messages[-1]["content"]
        assert "book dinner at 6pm" in sent
        assert "ran nextcloud_create" in sent


class TestPlaceholderLeakage:
    def test_literal_placeholder_raises_instead_of_becoming_data(self):
        """
        Regression: the planner copied the literal "<result_from_step_N>" from
        the prompt example, the numeric regex missed it, and a calendar event
        was created actually titled "<result_from_step_N>".
        """
        from agent.loop import _resolve_args
        with pytest.raises(ValueError, match="unresolved step placeholder"):
            _resolve_args({"summary": "<result_from_step_N>"}, {1: "Lunch"})

    def test_real_reference_still_resolves(self):
        from agent.loop import _resolve_args
        assert _resolve_args({"summary": "<result_from_step_1>"}, {1: "Lunch"}) == {"summary": "Lunch"}
