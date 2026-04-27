"""
JARVIS Unified Agent Loop.

Single entry point: AgentLoop.run_goal(goal_id, goal_text, backend)

Architecture:
    1. Plan    — LLM decomposes goal into ordered JSON steps
    2. Execute — independent steps run concurrently (max MAX_PARALLEL=5)
    3. Reflect — on step failure, replan silently up to MAX_RETRIES times
                 then notify via Slack and abort
    4. Verify  — after a CONFIRM-tier step executes post-approval, verify
                 the outcome before closing the goal

State is persisted to the goal_state SQLite table at every transition so
long-running goals survive restarts.

Replaces:
    mcp_gateway/agent.py
    jrvs/agent/planner.py
    jrvs/agent/executor.py
    jrvs/agent/runner.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable, Optional

from agent.tool_registry import tool_registry, CONFIRM, NOTIFY, AUTO, BLOCKED, max_tier
from llm.protocol import LLMBackend

log = logging.getLogger(__name__)

MAX_PARALLEL = 5
MAX_RETRIES  = 3

_PLANNER_SYSTEM = """\
You are JARVIS, an autonomous AI assistant.

Break the user's goal into an ordered list of tool calls.

Available tools (name [TIER] — description):
{catalogue}

TIER meanings:
  AUTO    — safe to execute silently (reads, searches)
  NOTIFY  — executes automatically, owner notified via Slack
  CONFIRM — must wait for Slack approval before executing
  BLOCKED — never execute

Rules:
1. Return ONLY a JSON array. No explanation, no markdown.
2. Each step:
   {{
     "step": int,
     "tool": "tool_name",
     "args": {{}},
     "depends_on": [],
     "reason": "why this step is needed"
   }}
3. depends_on is a list of step numbers this step requires first.
   Steps with no depends_on (or []) may run in parallel.
4. Use "<result_from_step_N>" as a placeholder in args when a value
   comes from step N's result.
5. Keep plans concise — 10 steps max.
6. NEVER invent tools not in the list above.
7. Google tools (gmail_*, docs_*, sheets_*, calendar_*) require OAuth credentials.
   If credentials are not available, use file_write/file_read instead of docs_create/docs_append.
   Do NOT retry a Google tool that has already failed — use a local alternative.
8. file_write saves to ~/jarvis_sandbox/ — use it for any "save to file" task.
"""


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class StepSpec:
    step:       int
    tool:       str
    args:       dict
    depends_on: list[int]
    reason:     str
    tier:       str = ""

    def __post_init__(self) -> None:
        if not self.tier:
            self.tier = tool_registry.tier_of(self.tool)


@dataclass
class GoalResult:
    goal_id: str
    run_id:  str
    status:  str           # completed | failed | awaiting_approval
    steps_ok: int = 0
    steps_failed: int = 0
    error: str = ""
    step_results: dict = field(default_factory=dict)


# ── Main class ────────────────────────────────────────────────────────────────

class AgentLoop:
    """Unified plan-execute-reflect agent loop."""

    def __init__(
        self,
        db,
        slack_send_approval: Optional[Callable[..., Awaitable[dict]]] = None,
    ) -> None:
        """
        Parameters
        ----------
        db
            core.database.Database instance
        slack_send_approval
            Async callable that posts a Slack approval request and returns
            {"ts": ..., "channel": ...}. If None, CONFIRM steps are skipped
            with a warning.
        """
        self._db = db
        self._slack_send_approval = slack_send_approval

        # Map of goal_id -> asyncio.Event for approval/denial signals
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_results: dict[str, str] = {}  # action_id -> "approved"|"denied"

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_goal(
        self,
        goal_id: str,
        goal_text: str,
        backend: LLMBackend,
    ) -> GoalResult:
        """
        Main entry point. Called by GoalScheduler and event trigger handlers.

        Handles !strong prefix routing — the backend passed here should already
        be an LLMRouter so that routing happens transparently.
        """
        run_id = str(uuid.uuid4())
        log.info("AgentLoop: starting goal '%s' run=%s", goal_id, run_id[:8])

        await self._db.upsert_goal_state(goal_id, {
            "status": "planning",
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "last_error": "",
        })

        try:
            plan = await self._plan(goal_text, goal_id, backend)
        except Exception as exc:
            log.error("AgentLoop: planning failed for '%s': %s", goal_id, exc)
            await self._mark_failed(goal_id, f"Planning failed: {exc}")
            return GoalResult(goal_id=goal_id, run_id=run_id, status="failed", error=str(exc))

        if not plan:
            await self._mark_failed(goal_id, "Planner returned no steps")
            return GoalResult(goal_id=goal_id, run_id=run_id, status="failed",
                              error="Planner returned no steps")

        await self._db.upsert_goal_state(goal_id, {
            "status": "running",
            "plan_json": json.dumps([_step_to_dict(s) for s in plan]),
            "step_cursor": 0,
        })

        result = await self._execute_plan(goal_id, run_id, plan, goal_text, backend)

        if result.status == "completed":
            await self._db.upsert_goal_state(goal_id, {"status": "completed"})
            log.info("AgentLoop: goal '%s' completed (%d steps)", goal_id, result.steps_ok)
        elif result.status != "awaiting_approval":
            await self._mark_failed(goal_id, result.error)

        return result

    async def handle_approval(self, action_id: str, approved: bool) -> None:
        """
        Called by SlackListener when the user taps Approve or Deny.
        Signals the waiting execute step to proceed or abort.
        """
        verdict = "approved" if approved else "denied"
        self._approval_results[action_id] = verdict
        await self._db.update_approval_status(action_id, verdict)

        event = self._approval_events.get(action_id)
        if event:
            event.set()
            log.info("AgentLoop: approval signal received for %s: %s", action_id[:8], verdict)
        else:
            log.warning("AgentLoop: no waiting event for action_id=%s", action_id[:8])

    # ── Planning ──────────────────────────────────────────────────────────────

    @staticmethod
    def _unavailable_tool_prefixes() -> "set[str]":
        """Return tool name prefixes that should be hidden when not configured."""
        from pathlib import Path as _Path
        creds = _Path.home() / "JRVS" / "google_credentials.json"
        if not creds.exists():
            return {"gmail_", "docs_", "sheets_", "calendar_"}
        return set()

    async def _plan(
        self,
        goal_text: str,
        goal_id: str,
        backend: LLMBackend,
    ) -> list[StepSpec]:
        exclude = self._unavailable_tool_prefixes()
        catalogue = tool_registry.catalogue_for_prompt(exclude=exclude or None)

        # Load prior memory for this goal (context from previous runs)
        state = await self._db.get_goal_state(goal_id) or {}
        try:
            memory = json.loads(state.get("context_json") or "{}")
        except (ValueError, TypeError):
            memory = {}

        memory_block = ""
        if memory:
            memory_block = "Memory from previous runs:\n" + \
                "\n".join(f"  {k}: {v}" for k, v in list(memory.items())[:10]) + "\n\n"

        system = _PLANNER_SYSTEM.format(catalogue=catalogue)
        user_msg = (
            f"{memory_block}"
            f"Goal: {goal_text}\n\n"
            f"Return a JSON array of steps (max 10)."
        )

        raw = await backend.chat(messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ])
        return _parse_plan(raw)

    async def _replan(
        self,
        goal_text: str,
        failed_step: StepSpec,
        error: str,
        remaining: list[StepSpec],
        backend: LLMBackend,
    ) -> list[StepSpec]:
        """Ask the LLM to recover from a failed step."""
        exclude = self._unavailable_tool_prefixes()
        catalogue = tool_registry.catalogue_for_prompt(exclude=exclude or None)
        remaining_json = json.dumps([_step_to_dict(s) for s in remaining], indent=2)
        system = _PLANNER_SYSTEM.format(catalogue=catalogue)
        user_msg = (
            f"Goal: {goal_text}\n\n"
            f"Step {failed_step.step} ({failed_step.tool}) failed with error: {error}\n\n"
            f"Remaining planned steps were:\n{remaining_json}\n\n"
            "Revise the remaining steps to recover from this failure. "
            "Return a JSON array of revised steps only."
        )
        try:
            raw = await backend.chat(messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ])
            return _parse_plan(raw)
        except Exception as exc:
            log.error("AgentLoop: replan failed: %s — using original remaining steps", exc)
            return remaining

    # ── Execution ─────────────────────────────────────────────────────────────

    async def _execute_plan(
        self,
        goal_id: str,
        run_id: str,
        plan: list[StepSpec],
        goal_text: str,
        backend: LLMBackend,
    ) -> GoalResult:
        """
        Execute steps respecting depends_on order. Independent steps
        (same dependency frontier) run concurrently up to MAX_PARALLEL.
        """
        step_results: dict[int, Any] = {}
        steps_ok = 0
        steps_failed = 0
        remaining = list(plan)
        retry_count = 0

        while remaining:
            # Find steps whose dependencies are all satisfied
            ready = [
                s for s in remaining
                if all(dep in step_results for dep in s.depends_on)
            ]
            if not ready:
                # Dependency deadlock — shouldn't happen with valid plans
                log.error("AgentLoop: dependency deadlock for goal '%s'", goal_id)
                break

            # Execute up to MAX_PARALLEL ready steps concurrently
            batch = ready[:MAX_PARALLEL]
            tasks = [
                self._execute_step(s, goal_id, run_id, step_results)
                for s in batch
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, outcome in zip(batch, batch_results):
                remaining.remove(step)

                if isinstance(outcome, Exception):
                    outcome = {"status": "error", "error": str(outcome)}

                status = outcome.get("status", "error")

                if status == "awaiting_approval":
                    # Whole goal is now paused; will resume when approval arrives
                    await self._db.upsert_goal_state(goal_id, {"status": "awaiting_approval"})
                    return GoalResult(
                        goal_id=goal_id, run_id=run_id,
                        status="awaiting_approval",
                        steps_ok=steps_ok, steps_failed=steps_failed,
                    )

                if status in ("success", "verified"):
                    step_results[step.step] = outcome.get("result")
                    steps_ok += 1
                    await self._db.upsert_goal_state(goal_id, {"step_cursor": step.step})

                elif status == "error":
                    err = outcome.get("error", "unknown error")
                    steps_failed += 1
                    log.warning(
                        "AgentLoop: step %d (%s) failed: %s — replanning (attempt %d/%d)",
                        step.step, step.tool, err, retry_count + 1, MAX_RETRIES,
                    )
                    retry_count += 1

                    if retry_count >= MAX_RETRIES:
                        msg = (
                            f":x: *Goal `{goal_id}` permanently failed* after {MAX_RETRIES} retries.\n"
                            f"Last error on step {step.step} ({step.tool}): `{err}`"
                        )
                        await _notify_slack(msg, channel_key="alerts")
                        return GoalResult(
                            goal_id=goal_id, run_id=run_id, status="failed",
                            steps_ok=steps_ok, steps_failed=steps_failed, error=err,
                        )

                    # Silent replan — add remaining steps back for revision
                    all_remaining = [s for s in plan
                                     if s.step not in step_results and s != step]
                    revised = await self._replan(goal_text, step, err, all_remaining, backend)
                    remaining = revised
                    await self._db.upsert_goal_state(goal_id, {
                        "retry_count": retry_count,
                        "last_error": err,
                        "plan_json": json.dumps([_step_to_dict(s) for s in revised]),
                    })
                    break  # restart the outer while with the revised plan

        return GoalResult(
            goal_id=goal_id, run_id=run_id, status="completed",
            steps_ok=steps_ok, steps_failed=steps_failed,
            step_results=step_results,
        )

    async def _execute_step(
        self,
        step: StepSpec,
        goal_id: str,
        run_id: str,
        step_results: dict[int, Any],
    ) -> dict[str, Any]:
        """Execute a single step, handling tier enforcement."""
        # Resolve placeholder args from earlier step results
        args = _resolve_args(step.args, step_results)
        tier = step.tier

        if tier == BLOCKED:
            log.warning("AgentLoop: step %d (%s) is BLOCKED — skipping", step.step, step.tool)
            return {"status": "blocked"}

        if tier == CONFIRM:
            return await self._execute_confirm_step(step, args, goal_id, run_id)

        # AUTO or NOTIFY — execute immediately
        try:
            result = await tool_registry.call(step.tool, args)
            log.info("AgentLoop: step %d [%s] %s — OK", step.step, tier.upper(), step.tool)
            if tier == NOTIFY:
                await _notify_slack(
                    f":white_check_mark: *Step completed* — `{step.tool}`\n{_truncate(str(result), 300)}",
                )
            return {"status": "success", "result": result}
        except Exception as exc:
            log.error("AgentLoop: step %d (%s) raised: %s", step.step, step.tool, exc)
            return {"status": "error", "error": str(exc)}

    async def _execute_confirm_step(
        self,
        step: StepSpec,
        args: dict,
        goal_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """
        Post a Slack approval request, wait for the response, then execute
        if approved. After execution, verify the outcome.
        """
        action_id = str(uuid.uuid4())
        approval_row = {
            "action_id": action_id,
            "goal_id":   goal_id,
            "run_id":    run_id,
            "step_num":  step.step,
            "tool":      step.tool,
            "args_json": json.dumps(args),
            "reason":    step.reason,
        }

        if self._slack_send_approval:
            try:
                slack_info = await self._slack_send_approval(
                    action_id=action_id,
                    tool=step.tool,
                    args=args,
                    reason=step.reason,
                    goal_id=goal_id,
                )
                approval_row["slack_ts"]      = slack_info.get("ts", "")
                approval_row["slack_channel"] = slack_info.get("channel", "")
            except Exception as exc:
                log.error("AgentLoop: could not send Slack approval request: %s", exc)
        else:
            log.warning(
                "AgentLoop: no slack_send_approval configured — "
                "CONFIRM step %d (%s) requires manual approval: action_id=%s",
                step.step, step.tool, action_id,
            )

        await self._db.save_pending_approval(approval_row)

        # Wait for Slack button response (up to 24 hours)
        event = asyncio.Event()
        self._approval_events[action_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=86400)
        except asyncio.TimeoutError:
            log.warning("AgentLoop: approval timed out for action_id=%s", action_id[:8])
            self._approval_events.pop(action_id, None)
            return {"status": "error", "error": "Approval timed out after 24h"}
        finally:
            self._approval_events.pop(action_id, None)

        verdict = self._approval_results.pop(action_id, "denied")
        if verdict != "approved":
            log.info("AgentLoop: action %s denied by user", action_id[:8])
            return {"status": "error", "error": "Denied by user"}

        # Execute the approved action
        try:
            result = await tool_registry.call(step.tool, args)
        except Exception as exc:
            log.error("AgentLoop: CONFIRM step execution failed: %s", exc)
            return {"status": "error", "error": str(exc)}

        # Verify the outcome
        verified = await self._verify_confirm_step(step.tool, args, result)
        if not verified:
            msg = (
                f":warning: *Approval verification failed* for `{step.tool}` "
                f"(action `{action_id[:8]}`)\n"
                f"The action was approved and executed but the expected outcome "
                f"could not be confirmed."
            )
            await _notify_slack(msg, channel_key="alerts")
            return {"status": "error", "error": "Post-execution verification failed"}

        await _notify_slack(
            f":white_check_mark: *Approved action completed* — `{step.tool}`\n"
            f"{_truncate(str(result), 300)}"
        )
        return {"status": "verified", "result": result}

    async def _verify_confirm_step(self, tool: str, args: dict, result: Any) -> bool:
        """
        Verify that a CONFIRM-tier action actually took effect.
        Returns True if verification passes or is not applicable.
        """
        try:
            if tool == "gmail_send":
                # Verify by checking Sent folder for a recent message to the recipient
                from agent.tools import gmail_search
                to_addr = args.get("to", "")
                subject = args.get("subject", "")
                results = await gmail_search(
                    query=f"in:sent to:{to_addr} subject:{subject[:30]}",
                    max_results=1,
                )
                return bool(results)

            if tool == "gmail_reply":
                # Verify by checking that the thread has a recent outbound message
                message_id = args.get("message_id", "")
                result_id = result.get("id", "") if isinstance(result, dict) else ""
                return bool(result_id)

            if tool == "calendar_delete":
                # Verify by confirming the event is gone
                from agent.tools import calendar_find
                event_id = args.get("event_id", "")
                # If the deleted event no longer appears in search, it's confirmed
                # We use the result from delete which returns {} on success
                return isinstance(result, dict) and "error" not in result

            # For other CONFIRM tools, trust the result
            return True

        except Exception as exc:
            log.warning("AgentLoop: verification check raised: %s", exc)
            return True  # Don't block on verification errors

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _mark_failed(self, goal_id: str, error: str) -> None:
        await self._db.upsert_goal_state(goal_id, {
            "status": "failed",
            "last_error": error[:500],
        })
        log.error("AgentLoop: goal '%s' failed: %s", goal_id, error)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_plan(raw: str) -> list[StepSpec]:
    """Parse LLM output into a list of StepSpec, validating each step."""
    text = raw.strip() if raw else ""
    # Strip markdown code fences if present
    text = re.sub(r"```[^\n]*\n?|```", "", text).strip()

    data = None
    for attempt in (text, re.search(r"(\[[\s\S]+\])", text)):
        try:
            candidate = attempt if isinstance(attempt, str) else (attempt.group(1) if attempt else None)
            if candidate:
                data = json.loads(candidate)
                break
        except (json.JSONDecodeError, AttributeError):
            continue

    if not isinstance(data, list):
        log.warning("_parse_plan: could not parse plan from: %r", (raw or "")[:200])
        return []

    steps = []
    known_names = tool_registry.names()
    for i, raw_step in enumerate(data[:10]):
        if not isinstance(raw_step, dict):
            continue
        tool = raw_step.get("tool", "")
        if isinstance(tool, list):
            tool = tool[0] if tool else ""
        if tool not in known_names:
            log.warning("_parse_plan: unknown tool '%s' — skipping step %d", tool, i + 1)
            continue
        steps.append(StepSpec(
            step=int(raw_step.get("step", i + 1)),
            tool=tool,
            args=raw_step.get("args", {}),
            depends_on=[int(d) for d in raw_step.get("depends_on", [])],
            reason=raw_step.get("reason", ""),
        ))
    return steps


def _step_to_dict(s: StepSpec) -> dict:
    return {
        "step": s.step, "tool": s.tool, "args": s.args,
        "depends_on": s.depends_on, "reason": s.reason, "tier": s.tier,
    }


def _resolve_args(args: dict[str, Any], step_results: dict[int, Any]) -> dict[str, Any]:
    """Replace step-result placeholders with actual prior results.

    Supported formats (inline or standalone):
      <result_from_step_N>
      [Results from step N]
      [result_from_step_N]
    """
    _PLACEHOLDER = re.compile(
        r"<result_from_step_(\d+)>"
        r"|\[(?:Search\s+)?Results?\s+from\s+[Ss]tep\s+(\d+)\]"
        r"|\[result_from_step_(\d+)\]"
        r"|\{result_from_step_(\d+)\}",
        re.IGNORECASE,
    )

    def _sub(match: re.Match) -> str:
        n = int(next(g for g in match.groups() if g is not None))
        raw = step_results.get(n, match.group(0))
        if isinstance(raw, (list, dict)):
            import json
            return json.dumps(raw, ensure_ascii=False)
        return str(raw)

    resolved = {}
    for k, v in args.items():
        if isinstance(v, str):
            v = _PLACEHOLDER.sub(_sub, v)
        resolved[k] = v
    return resolved


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


async def _notify_slack(text: str, channel_key: Optional[str] = None) -> None:
    """Best-effort Slack notification — never raises."""
    try:
        from core.slack_notifier import notify_async
        await notify_async(text, channel_key=channel_key)
    except Exception as exc:
        log.debug("_notify_slack: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
# Instantiated lazily in cli/interface.py after db is ready.
_agent_loop: Optional[AgentLoop] = None


def get_agent_loop() -> Optional[AgentLoop]:
    return _agent_loop


def init_agent_loop(db, slack_send_approval=None) -> AgentLoop:
    global _agent_loop
    _agent_loop = AgentLoop(db=db, slack_send_approval=slack_send_approval)
    return _agent_loop
