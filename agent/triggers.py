"""
JARVIS Event Trigger Hub.

Starts four background watchers that fire goals when real events happen,
rather than waiting for the next cron tick:

  1. Gmail push     — Gmail Pub/Sub push notifications via a local HTTP endpoint
  2. Slack mention  — @JARVIS or DM in Slack (already handled by slack_listener;
                      this module registers the goal-fire hook)
  3. Calendar watch — polls upcoming events every 5 min, fires 15 min before start
  4. File watch     — inotify-style watch on configured paths (uses watchfiles)

Each trigger resolves to a goal_id from goals.yaml (or creates an ad-hoc goal)
and hands it to AgentLoop.run_goal().

Usage (called from core/goal_scheduler.py)::

    from agent.triggers import TriggerHub
    hub = TriggerHub(db=db, agent_loop=loop, llm_backend=backend)
    await hub.start()
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any

import yaml

log = logging.getLogger(__name__)

_GOALS_FILE = Path(__file__).parent.parent / "goals.yaml"


def _load_goals() -> list[dict]:
    if not _GOALS_FILE.exists():
        return []
    try:
        data = yaml.safe_load(_GOALS_FILE.read_text()) or {}
        return data.get("goals", [])
    except Exception as exc:
        log.warning("TriggerHub: could not load goals.yaml: %s", exc)
        return []


def _find_goal_by_trigger(trigger: str) -> Optional[dict]:
    """Find the first enabled goal that has the given trigger in its triggers list."""
    for goal in _load_goals():
        if goal.get("enabled", True) and trigger in goal.get("triggers", []):
            return goal
    return None


class TriggerHub:
    """Manages all event-driven trigger watchers."""

    def __init__(self, db, agent_loop, llm_backend) -> None:
        self._db = db
        self._loop_obj = agent_loop       # AgentLoop instance
        self._backend = llm_backend       # LLMRouter / LLMBackend
        self._tasks: list[asyncio.Task] = []
        self._calendar_fired: set[str] = set()   # event IDs already fired
        self._gmail_history_id: Optional[str] = None

    async def start(self) -> None:
        """Start all trigger watchers as background tasks."""
        self._tasks = [
            asyncio.create_task(self._calendar_watcher(), name="trigger-calendar"),
            asyncio.create_task(self._gmail_watcher(),    name="trigger-gmail"),
            asyncio.create_task(self._file_watcher(),     name="trigger-file"),
        ]
        log.info("TriggerHub: started %d trigger watchers", len(self._tasks))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        log.info("TriggerHub: stopped")

    # ── Calendar: fire 15 min before events ──────────────────────────────────

    async def _calendar_watcher(self) -> None:
        """Poll Google Calendar every 5 minutes, fire goals 15 min before events."""
        log.info("TriggerHub: calendar watcher started")
        while True:
            try:
                await self._check_upcoming_events()
            except Exception as exc:
                log.warning("TriggerHub: calendar watcher error: %s", exc)
            await asyncio.sleep(300)  # 5 minutes

    async def _check_upcoming_events(self) -> None:
        from agent.tools import calendar_events
        now = datetime.now(timezone.utc)
        window_start = now + timedelta(minutes=14)
        window_end   = now + timedelta(minutes=16)

        try:
            events = await calendar_events(max_results=50)
        except Exception as exc:
            log.debug("TriggerHub: calendar_events failed: %s", exc)
            return

        for event in events:
            event_id = event.get("id", "")
            if not event_id or event_id in self._calendar_fired:
                continue

            start_str = event.get("start", "")
            if not start_str:
                continue

            try:
                # Parse ISO 8601; handle date-only events
                if "T" in start_str:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                else:
                    continue  # all-day event — skip countdown trigger
            except ValueError:
                continue

            if window_start <= start_dt <= window_end:
                self._calendar_fired.add(event_id)
                summary = event.get("summary", "Upcoming event")
                goal_text = (
                    f"An event is starting in 15 minutes: '{summary}' "
                    f"at {start_str}. Prepare a brief summary if there are "
                    f"relevant notes or documents, and send a Slack reminder."
                )
                log.info("TriggerHub: calendar trigger for '%s'", summary)
                await self._fire_adhoc_goal(
                    goal_id=f"calendar_trigger_{event_id[:12]}",
                    goal_text=goal_text,
                    channel_key="calendar",
                )

    # ── Gmail: poll for new mail matching trigger goals ───────────────────────

    async def _gmail_watcher(self) -> None:
        """Poll Gmail every 2 minutes for emails matching trigger criteria."""
        log.info("TriggerHub: Gmail watcher started (polling every 2 min)")
        while True:
            try:
                await self._check_gmail_triggers()
            except Exception as exc:
                log.warning("TriggerHub: Gmail watcher error: %s", exc)
            await asyncio.sleep(120)  # 2 minutes

    async def _check_gmail_triggers(self) -> None:
        """Check for trigger-type goals that have gmail_query defined."""
        goals = _load_goals()
        gmail_trigger_goals = [
            g for g in goals
            if g.get("enabled", True) and "gmail_push" in g.get("triggers", [])
            and g.get("gmail_query")
        ]
        if not gmail_trigger_goals:
            return

        from agent.tools import gmail_search
        for goal in gmail_trigger_goals:
            query = goal["gmail_query"]
            # Add a time filter to only get very recent emails (last 3 minutes)
            timed_query = f"{query} newer_than:3m"
            try:
                results = await gmail_search(query=timed_query, max_results=5)
            except Exception as exc:
                log.debug("TriggerHub: gmail_search failed for goal %s: %s", goal["id"], exc)
                continue

            if results:
                log.info(
                    "TriggerHub: Gmail trigger fired for goal '%s' (%d emails)",
                    goal["id"], len(results),
                )
                # Inject email summaries into goal context
                email_snippets = "\n".join(
                    f"- From: {r.get('from','')} | Subject: {r.get('subject','')} | "
                    f"{r.get('snippet','')[:100]}"
                    for r in results[:3]
                )
                augmented_goal = (
                    f"{goal['goal']}\n\nTriggered by {len(results)} new email(s):\n{email_snippets}"
                )
                await self._fire_goal(goal["id"], augmented_goal)

    # ── File watcher ─────────────────────────────────────────────────────────

    async def _file_watcher(self) -> None:
        """Watch configured paths for file changes using watchfiles."""
        watch_paths_env = os.environ.get("JARVIS_WATCH_PATHS", "")
        if not watch_paths_env:
            log.info("TriggerHub: file watcher disabled (JARVIS_WATCH_PATHS not set)")
            return

        watch_paths = [Path(p.strip()) for p in watch_paths_env.split(":") if p.strip()]
        valid_paths = [p for p in watch_paths if p.exists()]
        if not valid_paths:
            log.warning("TriggerHub: no valid watch paths in JARVIS_WATCH_PATHS")
            return

        try:
            from watchfiles import awatch
        except ImportError:
            log.warning(
                "TriggerHub: watchfiles not installed — file watcher disabled. "
                "Run: pip install watchfiles"
            )
            return

        log.info("TriggerHub: watching paths: %s", [str(p) for p in valid_paths])
        try:
            async for changes in awatch(*valid_paths):
                for change_type, path_str in changes:
                    await self._handle_file_change(path_str, str(change_type))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("TriggerHub: file watcher error: %s", exc)

    async def _handle_file_change(self, path: str, change_type: str) -> None:
        """React to a file system change by finding a matching goal."""
        goal = _find_goal_by_trigger("file_change")
        if not goal:
            # Create an ad-hoc goal
            goal_text = (
                f"A file was {change_type} at path: {path}. "
                f"Check if any action is needed (ingest, notify, process)."
            )
            await self._fire_adhoc_goal(
                goal_id=f"file_trigger_{abs(hash(path)) % 100000}",
                goal_text=goal_text,
                channel_key="alerts",
            )
        else:
            augmented = f"{goal['goal']}\n\nTriggered by file {change_type}: {path}"
            await self._fire_goal(goal["id"], augmented)

    # ── Slack trigger integration ─────────────────────────────────────────────

    def register_slack_goal_trigger(self, slack_listener) -> None:
        """
        Wire a secondary handler into SlackListener so that messages matching
        trigger goals are routed to AgentLoop in addition to normal chat.
        Called from cli/interface.py after both systems are initialised.
        """
        original_handler = slack_listener._handler

        async def _augmented_handler(message: str, session_id: str) -> str:
            # Check if any trigger goal matches this message
            goals = _load_goals()
            for goal in goals:
                if not goal.get("enabled", True):
                    continue
                if "slack_mention" not in goal.get("triggers", []):
                    continue
                keywords = goal.get("slack_keywords", [])
                if keywords and not any(kw.lower() in message.lower() for kw in keywords):
                    continue
                # Trigger this goal
                augmented = f"{goal['goal']}\n\nTriggered by Slack message: {message[:200]}"
                asyncio.create_task(self._fire_goal(goal["id"], augmented))

            # Always also run the normal chat handler
            if original_handler:
                return await original_handler(message, session_id)
            return "OK"

        slack_listener.set_handler(_augmented_handler)
        log.info("TriggerHub: Slack goal trigger registered")

    # ── Shared fire helpers ───────────────────────────────────────────────────

    async def _fire_goal(self, goal_id: str, goal_text: str) -> None:
        """Fire a named goal via AgentLoop."""
        try:
            await self._loop_obj.run_goal(
                goal_id=goal_id,
                goal_text=goal_text,
                backend=self._backend,
            )
        except Exception as exc:
            log.error("TriggerHub: error running goal '%s': %s", goal_id, exc)

    async def _fire_adhoc_goal(
        self,
        goal_id: str,
        goal_text: str,
        channel_key: Optional[str] = None,
    ) -> None:
        """Fire a goal that wasn't defined in goals.yaml."""
        log.info("TriggerHub: firing ad-hoc goal '%s'", goal_id)
        await self._fire_goal(goal_id, goal_text)
