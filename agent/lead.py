"""
JARVIS Lead Agent.

Decomposes a goal into role-tagged subtasks (agent/roles.py) and dispatches
each to its own independent, role-scoped AgentLoop sub-agent (agent/loop.py)
— its own planning conversation, scoped to just that role's tools — awaiting
and collecting results. Same lead-dispatches/sub-agents-run-independently
pattern as dispatching parallel exploration/implementation sub-agents:
the lead doesn't plan every atomic tool call itself, it hands scoped work to
a team member and waits for the result.

Single entry point: LeadAgent.run_goal(goal_id, goal_text, backend)
Same signature and GoalResult contract as AgentLoop.run_goal — a drop-in
replacement wherever agent.loop.get_agent_loop() is used (see
agent.loop.set_agent_loop()), so core/goal_scheduler.py, agent/triggers.py,
and cli/interface.py's Slack goal path need no changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from agent.approvals import ApprovalCoordinator, init_approval_coordinator
from agent.goal_check import check_goal_satisfied, SATISFIED
from agent.loop import AgentLoop, GoalResult, _notify_slack, _truncate, _planner_model
from agent.roles import ROLES, role_catalogue_for_prompt, tools_for_role
from agent.scheduling import next_ready_batch
from llm.protocol import LLMBackend

log = logging.getLogger(__name__)

MAX_PARALLEL = 5
DEFAULT_LEAD_MAX_RETRIES = 2
DEFAULT_ROLE_MAX_RETRIES = 2

_LEAD_SYSTEM = """\
You are the lead of a team of specialized JARVIS sub-agents.

Right now it is {today}. Resolve "tomorrow", "tonight", "next Friday" against it
and write the resolved date INTO the instruction, so the team member does not
have to guess.

Break the user's goal into an ordered list of subtasks, each assigned to
exactly one team member (role):

{roles}

Rules:
1. Return ONLY a JSON array. No explanation, no markdown.
2. Each subtask:
   {{
     "subtask": int,
     "role": "role_name",
     "instruction": "what this team member should do, in plain language",
     "depends_on": []
   }}
3. depends_on is a list of subtask numbers this one requires first.
   Subtasks with no depends_on (or []) may run in parallel.
4. Use "<result_from_subtask_N>" as a placeholder inside an instruction when
   it needs a result produced by subtask N.
5. DEFAULT TO ONE SUBTASK. Most goals are a single action and need exactly one.
   Only split when the goal genuinely cannot be done by one role. "Add a calendar
   event", "save this file", "send this email" are each ONE subtask.
6. Do ONLY what the user asked for. Never add work they did not request — no
   extra emails, notifications, images, reminders, confirmations, or follow-up
   steps. If the user asked for a calendar event, the entire plan is creating
   that calendar event. Inventing extra subtasks is a failure, not helpfulness.
7. Copy the concrete details from the goal into the instruction verbatim — the
   exact title/summary, date, time, and names the user gave. The team member
   cannot see the original goal, so a detail you omit is lost. Words after "make
   it" or "call it" are the event's title, not a separate task. If the user gave
   a specific time ("6pm"), that time MUST appear in the instruction. An event
   with a time is NOT an all-day event. Never write the words "all-day" in an
   instruction that also carries a clock time — that contradiction makes the
   team member drop the time. Never silently change, drop, or round a time or
   date the user gave you.
8. Keep the plan concise — 6 subtasks max, but prefer 1.
9. Only use role names from the list above. Never invent a role.
"""


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class SubtaskSpec:
    subtask:     int
    role:        str
    instruction: str
    depends_on:  list[int]


# ── Main class ────────────────────────────────────────────────────────────────

class LeadAgent:
    """Decomposes goals into role-tagged subtasks and dispatches them to
    independent role-scoped AgentLoop sub-agents."""

    def __init__(
        self,
        db,
        slack_send_approval=None,
        lead_max_retries: int = DEFAULT_LEAD_MAX_RETRIES,
        role_max_retries: int = DEFAULT_ROLE_MAX_RETRIES,
    ) -> None:
        self._db = db
        # One coordinator shared by every engine below, so a CONFIRM-tier
        # approval raised by any role (or the flat-legacy fallback engine)
        # resolves through the same Slack approve/deny signal.
        self._approvals: ApprovalCoordinator = init_approval_coordinator(db)
        self._lead_max_retries = lead_max_retries

        self._role_engines: dict[str, AgentLoop] = {
            role: AgentLoop(
                db=db,
                slack_send_approval=slack_send_approval,
                role=role,
                allowed_tools=tools_for_role(role),
                approvals=self._approvals,
                max_retries=role_max_retries,
            )
            for role in ROLES
        }

        # Kill-switch fallback for AGENT_TEAM_MODE=flat_legacy — a single
        # unscoped engine matching today's pre-refactor flat behaviour,
        # still wired to the shared coordinator so pending approvals aren't
        # orphaned if the mode is flipped mid-flight.
        self._flat_engine = AgentLoop(
            db=db, slack_send_approval=slack_send_approval, approvals=self._approvals,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_goal(self, goal_id: str, goal_text: str, backend: LLMBackend) -> GoalResult:
        """Main entry point. Called by GoalScheduler and event trigger handlers."""
        team_mode = os.environ.get("AGENT_TEAM_MODE", "auto")

        if team_mode == "flat_legacy":
            await self._db.upsert_goal_state(goal_id, {"mode": "flat"})
            return await self._flat_engine.run_goal(goal_id, goal_text, backend)

        log.info("LeadAgent: decomposing goal '%s'", goal_id)
        try:
            subtasks = await self._decompose(goal_text, backend)
        except Exception as exc:
            log.error(
                "LeadAgent: decomposition failed for '%s': %s — falling back to a single ops subtask",
                goal_id, exc,
            )
            subtasks = []

        if not subtasks:
            # Decomposition failed or returned nothing usable — treat the
            # whole goal as one generic subtask so a goal never silently
            # no-ops just because the lead's JSON parse failed.
            subtasks = [SubtaskSpec(subtask=1, role="ops", instruction=goal_text, depends_on=[])]

        # Fast path: a single subtask needs no dispatch machinery at all —
        # forward straight to that role engine under the SAME goal_id, and
        # return its result unmodified. Keeps single-domain goals (most of
        # today's goals.yaml) costing what they cost today, plus this one
        # small decomposition call.
        if len(subtasks) == 1:
            only = subtasks[0]
            await self._db.upsert_goal_state(goal_id, {"mode": "flat"})
            engine = self._role_engines.get(only.role, self._role_engines["ops"])
            # Pass the user's ORIGINAL wording alongside the rewritten
            # instruction. Decomposition is lossy — "tomorrow at 6pm" came back
            # as "create an all-day event" — so the outcome has to be audited
            # against what the user actually said, not against the paraphrase.
            return await engine.run_goal(
                goal_id, only.instruction, backend, original_request=goal_text,
            )

        run_id = str(uuid.uuid4())
        log.info(
            "LeadAgent: dispatching goal '%s' run=%s across %d subtasks",
            goal_id, run_id[:8], len(subtasks),
        )
        await self._db.upsert_goal_state(goal_id, {
            "status": "planning",
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "mode": "team",
            "plan_json": json.dumps([_subtask_to_dict(s) for s in subtasks]),
        })
        await self._db.upsert_goal_state(goal_id, {"status": "running"})

        result = await self._dispatch(goal_id, run_id, subtasks, goal_text, backend)

        # Audit the WHOLE goal here rather than inside each subtask: a subtask is
        # only ever part of the request, so checking one against the full request
        # would always report a gap. This is the multi-subtask equivalent of the
        # outer loop AgentLoop runs for single-subtask goals.
        if result.status == "completed":
            evidence = "\n".join(
                f"- subtask {s.subtask} [{s.role}]: {s.instruction}" for s in subtasks
            )
            verdict, missing = await check_goal_satisfied(
                goal_text, evidence, backend, planner_kwargs=_planner_model(),
            )
            if verdict != SATISFIED:
                log.warning(
                    "LeadAgent: goal '%s' ran but does not satisfy the request (%s): %s",
                    goal_id, verdict, missing,
                )
                result.status = "failed"
                result.error = f"completed subtasks but did not fulfil the request: {missing}"
                await self._db.upsert_goal_state(
                    goal_id, {"status": "failed", "last_error": result.error[:500]},
                )
                await _notify_slack(
                    f":warning: *Goal ran but did not fulfil the request* — `{goal_id}`\n{missing}",
                    channel_key="alerts",
                )
        return result

    async def handle_approval(self, action_id: str, approved: bool) -> None:
        """Called by SlackListener when the user taps Approve or Deny."""
        await self._approvals.handle_approval(action_id, approved)

    # ── Decomposition ────────────────────────────────────────────────────────

    async def _decompose(self, goal_text: str, backend: LLMBackend) -> list[SubtaskSpec]:
        system = _LEAD_SYSTEM.format(roles=role_catalogue_for_prompt(), today=_now_str())
        user_msg = f"Goal: {goal_text}\n\nReturn a JSON array of subtasks (max 6)."
        raw = await backend.chat(messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ], **_planner_model())
        return _parse_subtasks(raw)

    async def _replan(
        self,
        goal_text: str,
        failed_subtask: SubtaskSpec,
        error: str,
        remaining: list[SubtaskSpec],
        backend: LLMBackend,
    ) -> list[SubtaskSpec]:
        """Ask the LLM to recover from a failed subtask."""
        system = _LEAD_SYSTEM.format(roles=role_catalogue_for_prompt(), today=_now_str())
        remaining_json = json.dumps([_subtask_to_dict(s) for s in remaining], indent=2)
        user_msg = (
            f"Goal: {goal_text}\n\n"
            f"Subtask {failed_subtask.subtask} (role={failed_subtask.role}) failed with error: {error}\n\n"
            f"Remaining planned subtasks were:\n{remaining_json}\n\n"
            "Revise the remaining subtasks to recover from this failure. "
            "Return a JSON array of revised subtasks only."
        )
        try:
            raw = await backend.chat(**_planner_model(), messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ])
            return _parse_subtasks(raw)
        except Exception as exc:
            log.error("LeadAgent: replan failed: %s — using original remaining subtasks", exc)
            return remaining

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(
        self,
        goal_id: str,
        run_id: str,
        subtasks: list[SubtaskSpec],
        goal_text: str,
        backend: LLMBackend,
    ) -> GoalResult:
        """
        Dispatch subtasks respecting depends_on order. Independent subtasks
        (same dependency frontier) run concurrently up to MAX_PARALLEL, each
        as an awaited call into its role engine's own run_goal() — the same
        dispatch-and-collect pattern used for parallel sub-agent tool calls.
        """
        subtask_results: dict[int, GoalResult] = {}
        steps_ok = 0
        steps_failed = 0
        remaining = list(subtasks)
        original_subtasks = list(subtasks)
        retry_count = 0

        while remaining:
            batch = next_ready_batch(
                remaining, deps_fn=lambda s: s.depends_on,
                done_keys=subtask_results, max_parallel=MAX_PARALLEL,
            )
            if batch is None:
                log.error("LeadAgent: dependency deadlock for goal '%s'", goal_id)
                break

            tasks = [
                self._run_subtask(sub, goal_id, run_id, subtask_results, backend)
                for sub in batch
            ]
            batch_outcomes = await asyncio.gather(*tasks, return_exceptions=True)

            replanned = False
            for sub, outcome in zip(batch, batch_outcomes):
                remaining.remove(sub)

                if isinstance(outcome, Exception):
                    result = GoalResult(
                        goal_id=f"{goal_id}::{sub.subtask}", run_id=run_id,
                        status="failed", error=str(outcome),
                    )
                else:
                    result = outcome

                await self._db.save_subagent_state({
                    "goal_id": goal_id, "run_id": run_id,
                    "subtask_index": sub.subtask, "subtask": sub.instruction,
                    "role": sub.role, "status": result.status,
                    "result_summary": _truncate(result.error or f"{result.steps_ok} step(s) ok", 300),
                })

                if result.status == "awaiting_approval":
                    # Whole goal is now paused; will resume once the
                    # ApprovalCoordinator signals this subtask's engine.
                    # Sibling subtasks already dispatched in this batch have
                    # already completed (gather waits for the whole batch);
                    # subtasks not yet dispatched simply aren't started.
                    await self._db.upsert_goal_state(goal_id, {"status": "awaiting_approval"})
                    return GoalResult(
                        goal_id=goal_id, run_id=run_id, status="awaiting_approval",
                        steps_ok=steps_ok, steps_failed=steps_failed,
                    )

                if result.status == "completed":
                    subtask_results[sub.subtask] = result
                    steps_ok += result.steps_ok
                    steps_failed += result.steps_failed
                    continue

                # Subtask failed outright
                steps_failed += max(result.steps_failed, 1)
                retry_count += 1
                log.warning(
                    "LeadAgent: subtask %d (role=%s) failed: %s — replanning (attempt %d/%d)",
                    sub.subtask, sub.role, result.error, retry_count, self._lead_max_retries,
                )

                if retry_count >= self._lead_max_retries:
                    msg = (
                        f":x: *Goal `{goal_id}` permanently failed* after {self._lead_max_retries} "
                        f"lead-level retries.\nLast error on subtask {sub.subtask} "
                        f"(role={sub.role}): `{result.error}`"
                    )
                    await _notify_slack(msg, channel_key="alerts")
                    await self._mark_failed(goal_id, result.error or "subtask failed")
                    return GoalResult(
                        goal_id=goal_id, run_id=run_id, status="failed",
                        steps_ok=steps_ok, steps_failed=steps_failed, error=result.error,
                    )

                all_remaining = [
                    s for s in original_subtasks
                    if s.subtask not in subtask_results and s.subtask != sub.subtask
                ]
                revised = await self._replan(goal_text, sub, result.error or "unknown error", all_remaining, backend)
                remaining = revised if revised else all_remaining
                await self._db.upsert_goal_state(goal_id, {
                    "plan_json": json.dumps([_subtask_to_dict(s) for s in remaining]),
                })
                replanned = True
                break  # restart the outer while with the revised subtask list

            if replanned:
                continue

        await self._db.upsert_goal_state(goal_id, {"status": "completed"})
        log.info(
            "LeadAgent: goal '%s' completed — %d/%d subtasks ok",
            goal_id, len(subtask_results), len(original_subtasks),
        )
        return GoalResult(
            goal_id=goal_id, run_id=run_id, status="completed",
            steps_ok=steps_ok, steps_failed=steps_failed,
        )

    async def _run_subtask(
        self,
        sub: SubtaskSpec,
        goal_id: str,
        run_id: str,
        subtask_results: dict[int, GoalResult],
        backend: LLMBackend,
    ) -> GoalResult:
        """Dispatch one subtask to its role engine as an independent sub-agent run."""
        engine = self._role_engines.get(sub.role, self._role_engines["ops"])
        instruction = _resolve_instruction(sub.instruction, subtask_results)
        sub_goal_id = f"{goal_id}::{sub.subtask}"
        return await engine.run_goal(sub_goal_id, instruction, backend)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _mark_failed(self, goal_id: str, error: str) -> None:
        await self._db.upsert_goal_state(goal_id, {
            "status": "failed",
            "last_error": error[:500],
        })
        log.error("LeadAgent: goal '%s' failed: %s", goal_id, error)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _now_str() -> str:
    """Current local date/time, so the lead can resolve relative dates."""
    from datetime import datetime
    return datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")


def _parse_subtasks(raw: str) -> list[SubtaskSpec]:
    """Parse LLM output into a list of SubtaskSpec, validating each entry."""
    text = raw.strip() if raw else ""
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
        log.warning("_parse_subtasks: could not parse decomposition from: %r", (raw or "")[:200])
        return []

    subtasks = []
    for i, raw_sub in enumerate(data[:6]):
        if not isinstance(raw_sub, dict):
            continue
        role = raw_sub.get("role", "")
        if role not in ROLES:
            log.warning("_parse_subtasks: unknown role '%s' — skipping subtask %d", role, i + 1)
            continue
        instruction = raw_sub.get("instruction", "")
        if not instruction:
            continue
        subtasks.append(SubtaskSpec(
            subtask=int(raw_sub.get("subtask", i + 1)),
            role=role,
            instruction=instruction,
            depends_on=[int(d) for d in raw_sub.get("depends_on", [])],
        ))
    return subtasks


def _subtask_to_dict(s: SubtaskSpec) -> dict:
    return {
        "subtask": s.subtask, "role": s.role,
        "instruction": s.instruction, "depends_on": s.depends_on,
    }


def _resolve_instruction(instruction: str, subtask_results: "dict[int, GoalResult]") -> str:
    """Replace <result_from_subtask_N> placeholders with a short summary of subtask N's outcome."""
    _PLACEHOLDER = re.compile(r"<result_from_subtask_(\d+)>")

    def _sub(match: re.Match) -> str:
        n = int(match.group(1))
        result = subtask_results.get(n)
        if result is None:
            return match.group(0)
        if result.step_results:
            return "; ".join(f"{k}: {v}" for k, v in list(result.step_results.items())[:5])
        return f"(status={result.status}, {result.steps_ok} step(s) completed)"

    return _PLACEHOLDER.sub(_sub, instruction)
