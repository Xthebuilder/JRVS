"""
Goal Scheduler for JRVS — reads goals.yaml and runs them on schedule.

Supported schedules:
  morning  — fires once per day between 06:00–09:00
  hourly   — fires every 60 minutes
  daily    — fires once per day (noon)
  weekly   — fires once per week (Monday morning)
  manual   — never fires automatically; only via /agent run <id>

Usage (from CLI):
  /agent goals          — list all goals and their status
  /agent run <id>       — run a specific goal immediately
  /agent run-schedule morning|hourly|daily|weekly — run all matching goals
  /agent status         — show scheduler state and last-run times
"""
from __future__ import annotations

import asyncio
import logging
import re
import textwrap
from datetime import datetime, date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

log = logging.getLogger(__name__)

_GOALS_FILE = Path(__file__).parent.parent / "goals.yaml"

# ---------------------------------------------------------------------------
# Proactive goal proposal helpers
# ---------------------------------------------------------------------------

# Cheap keyword pre-filter — skip the LLM call when text clearly has no task.
_TASK_KEYWORDS = frozenset([
    "remind", "reminder", "schedule", "don't forget", "dont forget",
    "need to", "should", "have to", "must", "todo", "to-do",
    "follow up", "followup", "follow-up", "book", "call", "email",
    "send", "write", "draft", "prepare", "review", "check",
    "make sure", "set up", "setup", "fix", "finish", "complete",
    "deadline", "due", "by tomorrow", "by monday", "by friday",
    "appointment", "meeting", "standup", "sync",
])

_PROPOSE_SYSTEM = textwrap.dedent("""\
    You are a task-detection assistant for JARVIS.
    Your ONLY job: decide if the user's text contains an implied actionable task that
    JARVIS should remember and act on later (e.g. send an email, create a reminder,
    book something, follow up on something, research something).

    Respond with valid JSON only — no markdown, no explanation:
    {
      "is_task": true | false,
      "goal_text": "one plain-English sentence describing the task JARVIS should do",
      "suggested_id": "snake_case_slug_max_30_chars"
    }

    Rules:
    - is_task=false for casual chat, questions, or statements with no implied action.
    - is_task=true only when there is a clear pending action JARVIS can take.
    - goal_text should be imperative, specific, and reference any names/dates mentioned.
    - suggested_id must be unique-ish, lowercase, underscores only, max 30 chars.
""")


def _text_has_task_hint(text: str) -> bool:
    """Fast keyword scan before spending an LLM call."""
    lower = text.lower()
    return any(kw in lower for kw in _TASK_KEYWORDS)


def _append_goal_to_yaml(goal_dict: Dict[str, Any]) -> None:
    """Append a new goal entry to goals.yaml, preserving existing content."""
    if not _GOALS_FILE.exists():
        log.warning("goals.yaml not found — cannot append proposed goal.")
        return

    raw = _GOALS_FILE.read_text()
    data = yaml.safe_load(raw) or {}
    goals: list = data.get("goals", [])

    # Avoid duplicates by ID
    if any(g.get("id") == goal_dict["id"] for g in goals):
        return

    goals.append(goal_dict)
    data["goals"] = goals

    _GOALS_FILE.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    )


def _load_goals() -> List[Dict[str, Any]]:
    """Parse goals.yaml and return the list of goal dicts.

    Raises ValueError with a clear message when the file exists but is
    malformed, so callers can surface the error rather than silently returning
    empty and leaving goals permanently disabled.
    """
    if not _GOALS_FILE.exists():
        log.warning("goals.yaml not found at %s", _GOALS_FILE)
        return []
    try:
        data = yaml.safe_load(_GOALS_FILE.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"goals.yaml syntax error — fix the YAML: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read goals.yaml: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("goals.yaml must be a mapping with a top-level 'goals:' key.")
    goals = data.get("goals", [])
    if not isinstance(goals, list):
        raise ValueError("goals.yaml 'goals:' value must be a list.")

    for i, g in enumerate(goals):
        if not isinstance(g, dict):
            raise ValueError(f"goals.yaml entry #{i} is not a mapping.")
        if not g.get("id"):
            raise ValueError(f"goals.yaml entry #{i} is missing an 'id' field.")
        if not g.get("goal"):
            log.warning("goals.yaml goal '%s' has no 'goal' text and will be skipped.", g.get("id"))

    return goals


def get_pending_confirm_goals() -> List[Dict[str, Any]]:
    """Return enabled confirm-tier goals that have never been run.

    Used by the CLI to surface these at startup so the user knows they exist
    and need manual approval via /agent run <id>.
    """
    try:
        goals = _load_goals()
    except ValueError:
        return []
    return [
        g for g in goals
        if g.get("enabled", True)
        and g.get("tier") == "confirm"
        and g.get("goal")
    ]


def _schedule_matches(schedule_name: str) -> bool:
    """Return True if *now* is an appropriate time to fire this schedule."""
    now = datetime.now()
    weekday = now.weekday()  # 0 = Monday
    hour = now.hour

    if schedule_name == "morning":
        return 6 <= hour < 9
    if schedule_name == "hourly":
        return True  # caller controls interval
    if schedule_name == "daily":
        return hour == 12
    if schedule_name == "weekly":
        return weekday == 0 and 6 <= hour < 9
    if schedule_name == "manual":
        return False
    return False


class GoalScheduler:
    """Reads goals.yaml, executes goals via the LLM + MCP, tracks run history."""

    def __init__(self) -> None:
        self._llm_client = None
        self._last_run: Dict[str, Optional[datetime]] = {}
        self._last_run_date: Dict[str, Optional[date]] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # LLM client injection (set by CLI after startup)
    # ------------------------------------------------------------------

    def set_llm_client(self, client) -> None:
        self._llm_client = client
        log.info("GoalScheduler: LLM client injected (%s)", type(client).__name__)

    @property
    def _client(self):
        """Return the injected LLM client."""
        if self._llm_client is None:
            raise RuntimeError(
                "LLM client not injected — call set_llm_client() before using GoalScheduler."
            )
        return self._llm_client

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def list_goals(self) -> List[Dict[str, Any]]:
        """Return all goals annotated with last-run info."""
        try:
            goals = _load_goals()
        except ValueError as exc:
            log.error("list_goals: %s", exc)
            return []
        annotated = []
        for g in goals:
            gid = g.get("id", "")
            annotated.append({
                **g,
                "last_run": self._last_run.get(gid),
                "last_run_date": self._last_run_date.get(gid),
            })
        return annotated

    async def run_goal(self, goal_id: str) -> str:
        """Execute a single goal by ID. Returns a summary string."""
        try:
            goals = _load_goals()
        except ValueError as exc:
            return f"Cannot load goals.yaml: {exc}"
        goal = next((g for g in goals if g.get("id") == goal_id), None)
        if goal is None:
            return f"Goal '{goal_id}' not found in goals.yaml."
        if not goal.get("enabled", True):
            return f"Goal '{goal_id}' is disabled."
        return await self._execute_goal(goal)

    async def run_schedule(self, schedule_name: str) -> List[str]:
        """Execute all enabled goals that match the given schedule name."""
        try:
            goals = _load_goals()
        except ValueError as exc:
            return [f"Cannot load goals.yaml: {exc}"]
        results = []
        for goal in goals:
            if not goal.get("enabled", True):
                continue
            schedules = goal.get("schedules", [])
            if schedule_name in schedules:
                result = await self._execute_goal(goal)
                results.append(f"[{goal['id']}] {result}")
        return results if results else [f"No enabled goals match schedule '{schedule_name}'."]

    def get_status(self) -> Dict[str, Any]:
        goals = _load_goals()
        return {
            "scheduler_running": self._running,
            "goals_total": len(goals),
            "goals_enabled": sum(1 for g in goals if g.get("enabled", True)),
            "last_runs": {
                gid: dt.isoformat() if dt else None
                for gid, dt in self._last_run.items()
            },
        }

    # ------------------------------------------------------------------
    # Background scheduler loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background scheduling loop (idempotent)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="goal-scheduler")
        log.info("Goal scheduler started.")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Goal scheduler stopped.")

    async def _loop(self) -> None:
        """Check and fire scheduled goals every 60 seconds."""
        while self._running:
            try:
                try:
                    goals = _load_goals()
                except ValueError as exc:
                    log.error("Goal scheduler: %s — fix goals.yaml to resume scheduling.", exc)
                    await asyncio.sleep(60)
                    continue
                now = datetime.now()
                today = now.date()

                for goal in goals:
                    if not goal.get("enabled", True):
                        continue

                    gid = goal.get("id", "")
                    schedules = goal.get("schedules", [])

                    for sched in schedules:
                        if sched == "manual":
                            continue
                        if not _schedule_matches(sched):
                            continue

                        # Avoid running the same goal more than once per day
                        # (for daily/morning/weekly) or once per hour (for hourly)
                        last_date = self._last_run_date.get(gid)
                        last_dt = self._last_run.get(gid)

                        if sched == "hourly":
                            if last_dt and (now - last_dt).total_seconds() < 3590:
                                continue
                        else:
                            if last_date == today:
                                continue

                        log.info("Scheduler: firing goal '%s' (schedule=%s)", gid, sched)
                        result = await self._execute_goal(goal)
                        log.info("Scheduler: goal '%s' result: %s", gid, result[:200])
                        break  # one schedule match is enough per iteration

            except Exception as exc:
                log.error("Goal scheduler loop error: %s", exc)

            await asyncio.sleep(60)

    # ------------------------------------------------------------------
    # Goal execution
    # ------------------------------------------------------------------

    async def _execute_goal(self, goal: Dict[str, Any]) -> str:
        """Run a single goal dict through the LLM and return a summary."""
        gid = goal.get("id", "unknown")
        goal_text = goal.get("goal", "").strip()
        tier = goal.get("tier", "auto")
        slack_channel = goal.get("slack_channel")  # None = auto-route by content

        if not goal_text:
            return f"Goal '{gid}' has no goal text."

        # Substitute {date} placeholder
        goal_text = goal_text.replace("{date}", datetime.now().strftime("%Y-%m-%d"))

        # Goals at 'confirm' tier require human approval — skip in auto mode
        if tier == "confirm":
            log.debug(
                "Goal '%s' has tier=confirm — skipping automatic execution. "
                "Run manually with /agent run %s to review and approve.",
                gid, gid,
            )
            # Still mark as run so the hourly/daily guard doesn't fire again immediately
            self._last_run[gid] = datetime.now()
            self._last_run_date[gid] = datetime.now().date()
            return (
                f"Goal '{gid}' requires confirmation (tier=confirm). "
                f"Run /agent run {gid} to execute it interactively."
            )

        # Check if Google Workspace is needed but not available
        google_keywords = ["gmail", "google doc", "google sheet", "drive", "email"]
        needs_google = any(kw in goal_text.lower() for kw in google_keywords)
        if needs_google:
            try:
                from google_integration.client import google_workspace
                if not google_workspace.auth.is_authenticated():
                    return (
                        f"Goal '{gid}' requires Google Workspace but you are not authenticated. "
                        "Run /google-auth to set up credentials."
                    )
            except Exception:
                return f"Goal '{gid}' requires Google Workspace (not configured)."

        # Build system prompt for goal execution
        system_prompt = (
            "You are JARVIS executing an autonomous goal. "
            "Be concise and action-oriented. "
            "If you cannot complete a step, explain why briefly and continue with what you can do. "
            "Return a short summary of what was accomplished."
        )

        try:
            # First pass: use MCP agent for any tool calls needed
            from mcp_gateway.agent import mcp_agent
            agent_result = await mcp_agent.process_request(goal_text)

            # Build context from tool results
            context_parts = []
            if agent_result.get("tool_results"):
                for tr in agent_result["tool_results"]:
                    if tr.get("success") and tr.get("result"):
                        context_parts.append(
                            f"Tool {tr['server']}/{tr['tool']}:\n{str(tr['result'])[:2000]}"
                        )

            context = "\n\n".join(context_parts)

            # Second pass: generate a summary response
            response = await self._client.generate(
                prompt=goal_text,
                context=context,
                stream=False,
                system_prompt=system_prompt,
            )

            self._last_run[gid] = datetime.now()
            self._last_run_date[gid] = datetime.now().date()

            result = response or f"Goal '{gid}' executed (no response generated)."

            from core.slack_notifier import notify_async
            await notify_async(
                f":robot_face: *Goal completed* — `{gid}`\n{result[:400]}",
                channel_key=slack_channel,
            )

            return result

        except Exception as exc:
            log.error("Goal '%s' execution failed: %s", gid, exc, exc_info=True)

            from core.slack_notifier import notify_async
            await notify_async(
                f":x: *Goal failed* — `{gid}`\nError: {exc}",
                channel_key="alerts",
            )

            return f"Goal '{gid}' failed: {exc}"


    # ------------------------------------------------------------------
    # Proactive goal proposal — call from chat loop, audio sense, vision
    # ------------------------------------------------------------------

    async def propose_goal(
        self,
        text: str,
        source: str = "conversation",
        notify_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """
        Analyse *text* for implied actionable tasks.  If one is found, append
        it to goals.yaml as a confirm-tier / manual goal and optionally call
        *notify_callback* with a one-line summary for the user.

        Returns the new goal ID on success, or None if no task was detected.

        This is deliberately lightweight:
          1. Cheap keyword scan — skip LLM if no hint of a task.
          2. Small focused JSON prompt — no streaming, no RAG, minimal tokens.
          3. Fire-and-forget (callers should await but not block the main loop).
        """
        if not _text_has_task_hint(text):
            return None

        if self._llm_client is None:
            return None

        try:
            raw = await self._llm_client.generate(
                prompt=f"Text to analyse:\n{text.strip()[:800]}",
                context="",
                stream=False,
                system_prompt=_PROPOSE_SYSTEM,
            )
        except Exception as exc:
            log.debug("propose_goal: LLM call failed: %s", exc)
            return None

        if not raw:
            return None

        # Strip markdown fences if the model wrapped its JSON
        json_text = re.sub(r"```[^\n]*\n?|```", "", raw).strip()

        try:
            import json
            parsed = json.loads(json_text)
        except (ValueError, TypeError) as exc:
            log.debug("propose_goal: JSON parse failed (%s) — raw: %r", exc, raw[:200])
            return None

        if not parsed.get("is_task"):
            return None

        goal_text = str(parsed.get("goal_text", "")).strip()
        raw_id = str(parsed.get("suggested_id", "")).strip()

        if not goal_text or not raw_id:
            return None

        # Sanitise ID — lowercase, underscores, max 30 chars, ensure uniqueness
        safe_id = re.sub(r"[^a-z0-9_]", "_", raw_id.lower())[:28]
        ts_suffix = datetime.now().strftime("%m%d%H%M")
        goal_id = f"{safe_id}_{ts_suffix}"

        goal_dict: Dict[str, Any] = {
            "id": goal_id,
            "goal": goal_text,
            "schedules": ["manual"],
            "tier": "confirm",
            "enabled": True,
            "proposed_by": source,
            "proposed_at": datetime.now().isoformat(timespec="seconds"),
        }

        try:
            _append_goal_to_yaml(goal_dict)
        except Exception as exc:
            log.error("propose_goal: failed to write goals.yaml: %s", exc)
            return None

        log.info("propose_goal: added '%s' from %s — %r", goal_id, source, goal_text[:80])

        if notify_callback:
            try:
                notify_callback(
                    f"New task detected from {source}: \"{goal_text[:80]}\" "
                    f"— run /agent run {goal_id} to execute."
                )
            except Exception:
                pass

        return goal_id

    async def on_observation(self, text: str, source: str = "sense") -> Optional[str]:
        """
        Convenience wrapper for sensory inputs (audio/vision observations).
        Proposes a goal silently (no notify callback) so the background loop
        doesn't interrupt the user; the goal surfaces at next startup.
        """
        return await self.propose_goal(text, source=source)


# Global singleton
goal_scheduler = GoalScheduler()
