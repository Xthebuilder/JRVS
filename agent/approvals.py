"""
JARVIS Approval Coordinator — shared CONFIRM-tier approval bookkeeping.

Extracted from AgentLoop so that a lead agent and its role-scoped sub-agent
engines (agent/lead.py) can all route Slack approve/deny signals through one
place instead of each holding its own private, unreachable event registry.

Usage:
    from agent.approvals import init_approval_coordinator, get_approval_coordinator

    coordinator = init_approval_coordinator(db)   # once at startup
    ...
    verdict = await coordinator.wait_for_approval(action_id)   # inside an agent engine
    ...
    await coordinator.handle_approval(action_id, approved=True)  # from slack_listener
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)


class ApprovalCoordinator:
    """Tracks pending CONFIRM-tier approvals and signals waiters when resolved."""

    def __init__(self, db) -> None:
        self._db = db
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_results: dict[str, str] = {}

    async def wait_for_approval(self, action_id: str, timeout: int = 86400) -> str:
        """
        Block until a verdict is recorded for action_id (via handle_approval),
        or timeout seconds elapse. Returns "approved", "denied", or "timeout".
        """
        event = asyncio.Event()
        self._approval_events[action_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("ApprovalCoordinator: approval timed out for action_id=%s", action_id[:8])
            return "timeout"
        finally:
            self._approval_events.pop(action_id, None)

        return self._approval_results.pop(action_id, "denied")

    async def handle_approval(self, action_id: str, approved: bool) -> None:
        """
        Called by SlackListener when the user taps Approve or Deny.
        Signals the waiting execute step (in whichever agent engine owns it)
        to proceed or abort.
        """
        verdict = "approved" if approved else "denied"
        self._approval_results[action_id] = verdict
        await self._db.update_approval_status(action_id, verdict)

        event = self._approval_events.get(action_id)
        if event:
            event.set()
            log.info("ApprovalCoordinator: approval signal received for %s: %s", action_id[:8], verdict)
        else:
            log.warning("ApprovalCoordinator: no waiting event for action_id=%s", action_id[:8])


# ── Singleton ─────────────────────────────────────────────────────────────────
# Instantiated once at startup (cli/interface.py) and shared by every AgentLoop
# instance — the lead's own engine (if any) plus all role-scoped sub-agents.
_approval_coordinator: Optional[ApprovalCoordinator] = None


def get_approval_coordinator() -> Optional[ApprovalCoordinator]:
    return _approval_coordinator


def init_approval_coordinator(db) -> ApprovalCoordinator:
    global _approval_coordinator
    _approval_coordinator = ApprovalCoordinator(db)
    return _approval_coordinator
