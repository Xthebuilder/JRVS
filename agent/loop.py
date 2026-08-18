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

from agent.approvals import ApprovalCoordinator
from agent.scheduling import next_ready_batch
from agent.tool_registry import tool_registry, CONFIRM, NOTIFY, AUTO, BLOCKED, max_tier
from agent.verification import verify_action, VERIFIED, FAILED, UNVERIFIED
from llm.protocol import LLMBackend

log = logging.getLogger(__name__)

MAX_PARALLEL = 5
MAX_RETRIES  = 3

_PLANNER_SYSTEM = """\
You are JARVIS, an autonomous AI assistant.

Right now it is {today}.
Resolve every relative date against that — "tomorrow", "tonight", "next Friday",
"in an hour". Never guess a date from memory: without this line the planner has
no idea what day it is and silently books events years in the past. Write dates
as ISO 8601 with the time included, e.g. 2026-08-18T18:00:00 for 6pm tomorrow.
Only use a date-only value when the user actually asked for an all-day event.

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
   Do NOT retry a Google tool that has already failed — use the local alternative
   for that same kind of work: nextcloud_* for anything calendar, file_write for
   documents and notes.
8. CALENDAR WORK USES THE nextcloud_* TOOLS. To put an event on the calendar you
   MUST include a nextcloud_create step — that is the step that actually creates
   it. nextcloud_list_calendars and nextcloud_find only look; on their own they
   change nothing. Use nextcloud_update to change an event and nextcloud_delete
   to remove one.
9. file_write saves text to ~/jrvs-workspace/ — use it for "save this to a file"
   tasks only. It is NEVER a substitute for a real action. If the user asked for a
   calendar event, an email, or anything else in the world, writing a file does not
   fulfil that request — plan the tool that actually performs it.
10. Every plan must contain the step that performs what the user asked for. Reading
   and searching steps are optional; the acting step is not.
"""


def _planner_model() -> "dict[str, str]":
    """Extra kwargs pinning planning calls to a stronger model.

    Planning is where a small local model fails: nemo:12b executes a good plan
    fine but authors bad ones. Planning is also only a couple of calls per goal,
    so a slower, better model is affordable here in a way it is not for chat.
    Set JRVS_PLANNER_MODEL to enable; unset means plan with the default model.
    """
    import os
    model = os.environ.get("JRVS_PLANNER_MODEL", "").strip()
    if not model:
        return {}
    # Keep the planner resident just long enough to cover one planning burst,
    # then let it go. A goal calls it twice in quick succession — LeadAgent
    # decomposes, then AgentLoop plans — and gpt-oss:20b costs ~25s to load
    # because at 13GB it does not fit a 12GB card and spills to CPU. Unloading
    # between those two calls pays that twice; holding it for the default 5m
    # instead evicts the small model that serves chat and every tool step. A
    # short window spans the burst and frees the GPU before execution.
    return {"model": model, "keep_alive": os.environ.get("JRVS_PLANNER_KEEP_ALIVE", "90s")}


def _now_str() -> str:
    """Current local date/time for the planner prompt.

    The planner had no clock at all, so "tomorrow at 6pm" resolved to whatever
    the model guessed — it once booked an event for 2024-07-18.
    """
    from datetime import datetime
    return datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")


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
        role: str = "general",
        allowed_tools: Optional["set[str]"] = None,
        approvals: Optional[ApprovalCoordinator] = None,
        max_retries: int = MAX_RETRIES,
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
        role
            Name of this engine's role, used for logging/tracing when several
            AgentLoop instances run as role-scoped sub-agents under a LeadAgent
            (agent/lead.py). Defaults to "general" for standalone/flat usage.
        allowed_tools
            If given, restricts planning and execution to this subset of
            registered tool names (a role's scope). None means every
            registered tool is available, preserving today's flat behaviour.
        approvals
            Shared ApprovalCoordinator to route CONFIRM-tier approvals
            through. If None, a private one is constructed so AgentLoop
            remains usable standalone.
        max_retries
            Replan budget for this engine. Defaults to MAX_RETRIES so
            standalone/flat usage is unchanged; role engines under a
            LeadAgent are typically given a smaller budget to bound total
            lead+role retry cost.
        """
        self._db = db
        self._slack_send_approval = slack_send_approval
        self._role = role
        self._allowed_tools = allowed_tools
        self._max_retries = max_retries
        self._approvals = approvals or ApprovalCoordinator(db)

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
        log.info("AgentLoop[%s]: starting goal '%s' run=%s", self._role, goal_id, run_id[:8])

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
            log.info("AgentLoop[%s]: goal '%s' completed (%d steps)", self._role, goal_id, result.steps_ok)
        elif result.status != "awaiting_approval":
            await self._mark_failed(goal_id, result.error)

        return result

    async def handle_approval(self, action_id: str, approved: bool) -> None:
        """
        Called by SlackListener when the user taps Approve or Deny.
        Thin passthrough to the shared ApprovalCoordinator — kept here so
        code holding a bare AgentLoop reference (standalone/flat usage)
        doesn't need to know about ApprovalCoordinator directly.
        """
        await self._approvals.handle_approval(action_id, approved)

    # ── Planning ──────────────────────────────────────────────────────────────

    @staticmethod
    def _unavailable_tool_prefixes() -> "set[str]":
        """Return tool name prefixes that should be hidden when not configured."""
        from pathlib import Path as _Path
        creds = _Path.home() / "JRVS" / "google_credentials.json"
        if not creds.exists():
            return {"gmail_", "docs_", "sheets_", "calendar_"}
        return set()

    def _effective_exclude_prefixes(self) -> "set[str]":
        """Merge credential-based exclusion with this engine's role scope, if any."""
        exclude = set(self._unavailable_tool_prefixes())
        if self._allowed_tools is not None:
            exclude |= (tool_registry.names() - self._allowed_tools)
        return exclude

    async def _plan(
        self,
        goal_text: str,
        goal_id: str,
        backend: LLMBackend,
    ) -> list[StepSpec]:
        exclude = self._effective_exclude_prefixes()
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

        system = _PLANNER_SYSTEM.format(catalogue=catalogue, today=_now_str())
        user_msg = (
            f"{memory_block}"
            f"Goal: {goal_text}\n\n"
            f"Return a JSON array of steps (max 10)."
        )

        raw = await backend.chat(messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ], **_planner_model())
        return _parse_plan(raw, allowed_names=self._allowed_tools)

    async def _replan(
        self,
        goal_text: str,
        failed_step: StepSpec,
        error: str,
        remaining: list[StepSpec],
        backend: LLMBackend,
    ) -> list[StepSpec]:
        """Ask the LLM to recover from a failed step."""
        exclude = self._effective_exclude_prefixes()
        catalogue = tool_registry.catalogue_for_prompt(exclude=exclude or None)
        remaining_json = json.dumps([_step_to_dict(s) for s in remaining], indent=2)
        system = _PLANNER_SYSTEM.format(catalogue=catalogue, today=_now_str())
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
            ], **_planner_model())
            return _parse_plan(raw, allowed_names=self._allowed_tools)
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
            # Find the next batch of steps whose dependencies are satisfied
            batch = next_ready_batch(
                remaining, deps_fn=lambda s: s.depends_on,
                done_keys=step_results, max_parallel=MAX_PARALLEL,
            )
            if batch is None:
                # Dependency deadlock — shouldn't happen with valid plans
                log.error("AgentLoop[%s]: dependency deadlock for goal '%s'", self._role, goal_id)
                break

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
                        "AgentLoop[%s]: step %d (%s) failed: %s — replanning (attempt %d/%d)",
                        self._role, step.step, step.tool, err, retry_count + 1, self._max_retries,
                    )
                    retry_count += 1

                    if retry_count >= self._max_retries:
                        msg = (
                            f":x: *Goal `{goal_id}` permanently failed* after {self._max_retries} retries.\n"
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

        # Defense-in-depth: a role-scoped engine's plan should already be
        # limited to its allowed tools (via _parse_plan's allowed_names), but
        # don't rely solely on the planner behaving — re-check before execution.
        if self._allowed_tools is not None and step.tool not in self._allowed_tools:
            log.warning(
                "AgentLoop[%s]: step %d tool '%s' is outside role scope — rejecting",
                self._role, step.step, step.tool,
            )
            return {"status": "error", "error": f"tool '{step.tool}' outside role scope"}

        if tier == BLOCKED:
            log.warning("AgentLoop: step %d (%s) is BLOCKED — skipping", step.step, step.tool)
            return {"status": "blocked"}

        if tier == CONFIRM:
            return await self._execute_confirm_step(step, args, goal_id, run_id)

        # AUTO or NOTIFY — execute immediately
        try:
            result = await tool_registry.call(step.tool, args)

            # Tools report expected failures by returning {"error": ...} rather
            # than raising. Only exceptions were treated as failures, so a step
            # could return "content is empty", be logged OK, and the whole goal
            # reported complete while nothing happened. Surface it as an error
            # so the loop replans with the tool's own message as the hint.
            if isinstance(result, dict) and result.get("error"):
                log.warning(
                    "AgentLoop: step %d (%s) returned an error: %s",
                    step.step, step.tool, result["error"],
                )
                return {"status": "error", "error": str(result["error"])}

            status, detail = await verify_action(step.tool, args, result)
            if status == FAILED:
                log.error(
                    "AgentLoop: step %d (%s) reported success but verification failed: %s",
                    step.step, step.tool, detail,
                )
                return {
                    "status": "error",
                    "error": f"{step.tool} reported success but did not take effect: {detail}",
                }

            log.info(
                "AgentLoop: step %d [%s] %s — OK (%s)",
                step.step, tier.upper(), step.tool, status,
            )
            if tier == NOTIFY:
                mark = ":white_check_mark:" if status == VERIFIED else ":grey_question:"
                suffix = "" if status == VERIFIED else "  _(not independently verified)_"
                await _notify_slack(
                    f"{mark} *Step completed* — `{step.tool}`{suffix}\n{_truncate(str(result), 300)}",
                )
            return {"status": "success", "result": result, "verification": status}
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

        # Wait for Slack button response (up to 24 hours), via the shared
        # ApprovalCoordinator so this resolves regardless of which role
        # engine (or the lead) is holding the waiting coroutine.
        verdict = await self._approvals.wait_for_approval(action_id, timeout=86400)
        if verdict == "timeout":
            log.warning("AgentLoop[%s]: approval timed out for action_id=%s", self._role, action_id[:8])
            return {"status": "error", "error": "Approval timed out after 24h"}

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
        status, detail = await verify_action(step.tool, args, result)
        if status == FAILED:
            msg = (
                f":warning: *Approval verification failed* for `{step.tool}` "
                f"(action `{action_id[:8]}`)\n{detail}"
            )
            await _notify_slack(msg, channel_key="alerts")
            return {"status": "error", "error": f"Post-execution verification failed: {detail}"}

        await _notify_slack(
            f":white_check_mark: *Approved action completed* — `{step.tool}`\n"
            f"{_truncate(str(result), 300)}"
        )
        return {"status": "verified", "result": result}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _mark_failed(self, goal_id: str, error: str) -> None:
        await self._db.upsert_goal_state(goal_id, {
            "status": "failed",
            "last_error": error[:500],
        })
        log.error("AgentLoop: goal '%s' failed: %s", goal_id, error)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_plan(raw: str, allowed_names: "Optional[set[str]]" = None) -> list[StepSpec]:
    """Parse LLM output into a list of StepSpec, validating each step.

    allowed_names, when given, restricts which tool names are accepted —
    used by role-scoped engines so an out-of-role tool the LLM hallucinates
    (or is prompt-injected into emitting) is rejected at parse time, on top
    of the prompt already hiding it via the catalogue's exclude set.
    """
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
    known_names = allowed_names if allowed_names is not None else tool_registry.names()
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


def get_agent_loop():
    return _agent_loop


def init_agent_loop(db, slack_send_approval=None) -> AgentLoop:
    global _agent_loop
    _agent_loop = AgentLoop(db=db, slack_send_approval=slack_send_approval)
    return _agent_loop


def set_agent_loop(instance) -> None:
    """
    Install a pre-built orchestrator (e.g. a LeadAgent from agent/lead.py) as
    the process-wide singleton returned by get_agent_loop(). Lets callers that
    only need run_goal()/handle_approval() — core/goal_scheduler.py,
    agent/triggers.py, cli/interface.py's Slack goal path — stay unchanged
    regardless of whether a flat AgentLoop or a LeadAgent is running the show.
    """
    global _agent_loop
    _agent_loop = instance
