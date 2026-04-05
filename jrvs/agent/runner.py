"""
JRVS Agent — Main orchestrator.

Workflow (per goal):
  1. Load goals for the requested schedule.
  2. Retrieve persistent memory from DB.
  3. Optionally gather live context (latest email snippet, YT stats).
  4. Ask Planner to produce a step list.
  5. Execute steps in order via Executor (tier rules enforced).
  6. Persist updated memory (insights from results).
  7. Summarise results via Ollama.
  8. If AGENT_NOTIFY_EMAIL set: send digest email.
  9. Save run record to DB.
 10. Return list of RunResult dicts to the CLI.

Pause flag:  touch ~/JRVS/agent.pause  →  runner exits immediately.
Dry-run flag: shows plan without any API calls.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_PAUSE_FILE = Path.home() / "JRVS" / "agent.pause"


@dataclass
class RunResult:
    goal_id:   str
    run_id:    str
    status:    str                        # success / partial / error / dry_run / skipped
    plan:      list[dict[str, Any]]      = field(default_factory=list)
    results:   list[dict[str, Any]]      = field(default_factory=list)
    summary:   str                        = ""
    error:     str                        = ""


class AgentRunner:
    """Orchestrate goal planning + execution for a given schedule."""

    def __init__(
        self,
        db=None,
        planner=None,
        executor=None,
        dry_run: bool = False,
    ) -> None:
        from jrvs.storage.database import Database
        from jrvs.agent.planner  import Planner
        from jrvs.agent.executor import Executor

        self._db      = db       or Database()
        self._planner = planner  or Planner()
        self._dry_run = dry_run
        self._executor = executor or Executor(db=self._db, dry_run=dry_run)

    # ── Entry points ──────────────────────────────────────────────────────────

    def run(
        self,
        schedule:  str  = "manual",
        goal_id:   str  | None = None,
    ) -> list[RunResult]:
        """Run all goals for *schedule*.  Pass *goal_id* to run a single goal."""
        if _is_paused():
            log.info("Agent is paused (remove ~/JRVS/agent.pause to resume).")
            return []

        from jrvs.agent.goals import GoalLoader
        loader = GoalLoader()

        goals: list[dict[str, Any]]
        if goal_id:
            g = loader.get(goal_id)
            goals = [g] if g else []
        else:
            goals = loader.for_schedule(schedule)

        if not goals:
            log.info("No goals found for schedule '%s'.", schedule)
            return []

        results: list[RunResult] = []
        for goal in goals:
            try:
                r = self._run_goal(goal)
            except Exception as exc:
                r = RunResult(
                    goal_id=goal.get("id", "?"),
                    run_id=str(uuid.uuid4()),
                    status="error",
                    error=str(exc),
                )
                log.exception("Unhandled error running goal '%s'", goal.get("id"))
            results.append(r)
        return results

    # ── Single-goal pipeline ──────────────────────────────────────────────────

    def _run_goal(self, goal: dict[str, Any]) -> RunResult:
        goal_id   = goal["id"]
        goal_text = goal.get("goal", "")
        tier      = goal.get("tier", "notify")
        run_id    = str(uuid.uuid4())

        log.info("Running goal '%s' (run_id=%s, tier=%s)", goal_id, run_id[:8], tier)

        # 1. Fetch memory
        memory = self._db.get_agent_memory(goal_id) or {}

        # 2. Gather brief live context
        context = self._gather_context(goal)

        # 3. Plan
        plan = self._planner.plan(goal_text + "\n" + context, memory=memory)
        if not plan:
            log.warning("Planner returned empty plan for goal '%s'", goal_id)
            return RunResult(goal_id=goal_id, run_id=run_id, status="error",
                             error="Planner returned no steps")

        # Save initial run record
        self._db.upsert_agent_run({
            "run_id":     run_id,
            "goal_id":    goal_id,
            "goal_text":  goal_text,
            "schedule":   ", ".join(goal.get("schedules", [])),
            "status":     "running" if not self._dry_run else "dry_run",
            "plan_json":  json.dumps(plan),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "summary":    "",
            "error":      "",
        })

        # 4. Execute steps
        step_results: dict[int, Any] = {}
        action_results: list[dict[str, Any]] = []
        any_error = False
        for step in plan:
            res = self._executor.execute_step(
                step, run_id,
                goal_tier_override=tier,
                step_results=step_results,
            )
            action_results.append(res)
            if res.get("status") == "success":
                step_results[step["step"]] = res.get("result")
            elif res.get("status") == "error":
                any_error = True
                # Try replan
                remaining = [s for s in plan if s["step"] > step["step"]]
                if remaining:
                    revised = self._planner.replan(
                        goal_text, step, res.get("error", ""), remaining
                    )
                    # Swap remaining steps
                    plan = [s for s in plan if s["step"] <= step["step"]] + revised

        # 5. Update memory
        self._update_memory(goal_id, step_results, action_results)

        # 6. Summarise
        summary = self._summarise(goal_text, action_results)

        # 7. Persist final run record
        status = "dry_run" if self._dry_run else ("partial" if any_error else "success")
        self._db.upsert_agent_run({
            "run_id":     run_id,
            "goal_id":    goal_id,
            "goal_text":  goal_text,
            "schedule":   ", ".join(goal.get("schedules", [])),
            "status":     status,
            "plan_json":  json.dumps(plan),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "summary":    summary,
            "error":      "",
        })

        # 8. Notify (digest email) for NOTIFY+ tier goals
        if not self._dry_run and tier in ("notify", "confirm"):
            self._send_digest(goal_id, run_id, summary, action_results)

        return RunResult(
            goal_id=goal_id,
            run_id=run_id,
            status=status,
            plan=plan,
            results=action_results,
            summary=summary,
        )

    # ── Context gathering ─────────────────────────────────────────────────────

    def _gather_context(self, goal: dict[str, Any]) -> str:
        """Optionally inject a short live context snippet into the prompt."""
        text = goal.get("goal", "").lower()
        lines: list[str] = []

        # Hints: detect what the goal likely needs
        needs_email = any(w in text for w in ("email", "inbox", "gmail", "unread"))
        needs_yt    = any(w in text for w in ("youtube", "channel", "video", "analytics"))

        if needs_email:
            lines.append(_safe_context("recent emails", self._peek_gmail))
        if needs_yt:
            lines.append(_safe_context("YouTube stats", self._peek_youtube))

        return "\n".join(filter(None, lines))

    def _peek_gmail(self) -> str:
        from jrvs.google.google_agent import GoogleAgent
        ga = GoogleAgent()
        res = ga._execute([{"name": "gmail_list", "args": {"max_results": 3}}])
        if isinstance(res, list):
            return "; ".join(str(e.get("subject", ""))[:60] for e in res[:3])
        return str(res)[:200]

    def _peek_youtube(self) -> str:
        from jrvs.storage.database import Database
        db = Database()
        rows = db.get_recent_runs(limit=1)
        if rows:
            return f"last run: {rows[0].get('created_at', '')}"
        return ""

    # ── Memory update ─────────────────────────────────────────────────────────

    def _update_memory(
        self,
        goal_id: str,
        step_results: dict[int, Any],
        action_results: list[dict[str, Any]],
    ) -> None:
        from jrvs.config import Config
        from jrvs.llm.ollama_client import OllamaClient
        if not step_results:
            return
        summary_prompt = (
            "From these tool results, extract 3-5 KEY FACTS worth remembering "
            "for the next run of this goal. Return a JSON object with string keys "
            "and short string values (max 80 chars each). No explanation.\n\n"
            f"Results:\n{str(list(step_results.values())[:5])[:1000]}"
        )
        try:
            llm = OllamaClient()
            raw = llm.chat(messages=[
                {"role": "system", "content": "You are a concise memory extractor."},
                {"role": "user",   "content": summary_prompt},
            ])
            import json, re
            m = re.search(r"\{[\s\S]+\}", raw)
            if m:
                facts = json.loads(m.group())
                for k, v in facts.items():
                    self._db.set_agent_memory(goal_id, str(k), str(v)[:200])
        except Exception as exc:
            log.debug("Memory update skipped: %s", exc)

    # ── Summarise ─────────────────────────────────────────────────────────────

    def _summarise(
        self,
        goal_text: str,
        action_results: list[dict[str, Any]],
    ) -> str:
        from jrvs.llm.ollama_client import OllamaClient
        completed = [r for r in action_results if r.get("status") == "success"]
        pending   = [r for r in action_results if r.get("status") == "awaiting_approval"]
        errors    = [r for r in action_results if r.get("status") == "error"]

        prompt = (
            f"Goal: {goal_text}\n\n"
            f"Completed {len(completed)} steps successfully. "
            f"{len(pending)} action(s) awaiting approval. "
            f"{len(errors)} error(s).\n\n"
            "Write a 2-3 sentence plain-English summary of what was accomplished."
        )
        try:
            llm = OllamaClient()
            return llm.chat(messages=[
                {"role": "system", "content": "You are a concise task summariser."},
                {"role": "user",   "content": prompt},
            ]).strip()
        except Exception as exc:
            log.debug("Summarise failed: %s", exc)
            return (
                f"Completed {len(completed)} step(s), "
                f"{len(pending)} pending approval, "
                f"{len(errors)} error(s)."
            )

    # ── Digest email ──────────────────────────────────────────────────────────

    def _send_digest(
        self,
        goal_id: str,
        run_id: str,
        summary: str,
        action_results: list[dict[str, Any]],
    ) -> None:
        from jrvs.config import Config
        notify = Config.AGENT_NOTIFY_EMAIL
        if not notify:
            return

        pending = [r for r in action_results if r.get("status") == "awaiting_approval"]
        subject = f"[JRVS] {goal_id} completed (run {run_id[:8]})"
        body = f"{summary}\n"
        if pending:
            body += (
                f"\n{len(pending)} action(s) require your approval:\n"
                + "\n".join(
                    f"  jrvs agent approve {r['action_id']}" for r in pending
                )
                + "\n\nRun  jrvs agent pending  for details.\n"
            )
        try:
            from jrvs.google.google_agent import GoogleAgent
            ga = GoogleAgent()
            ga._execute([{
                "name": "gmail_send",
                "args": {"to": notify, "subject": subject, "body": body},
            }])
        except Exception as exc:
            log.warning("Could not send digest email: %s", exc)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _is_paused() -> bool:
    return _PAUSE_FILE.exists()


def pause_agent() -> None:
    _PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PAUSE_FILE.touch()


def resume_agent() -> None:
    _PAUSE_FILE.unlink(missing_ok=True)


def _safe_context(label: str, fn) -> str:
    try:
        return f"[{label}] {fn()}"
    except Exception:
        return ""
