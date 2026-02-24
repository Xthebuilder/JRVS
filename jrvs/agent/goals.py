"""
JRVS Agent — Goal loader and scheduler.

Goals are defined in ~/JRVS/goals.yaml with this structure:

    goals:
      - id: morning_digest
        text: "Every morning summarise my unread emails and save to a Google Doc"
        schedules: [morning]       # morning / hourly / daily / weekly / manual
        enabled: true
        tier: notify               # auto / notify / confirm (override global default)

      - id: weekly_analytics
        text: "Every Sunday analyse @MyChannel and email me the growth report"
        schedules: [weekly]
        enabled: true
        tier: notify

      - id: urgent_email_watch
        text: "If any email mentions 'urgent' draft a reply and show it to me"
        schedules: [hourly]
        enabled: true
        tier: confirm

Schedule labels used in cron / CLI:
    morning  — runs at ~8 AM daily
    hourly   — runs every hour
    daily    — runs once a day (any time)
    weekly   — runs on Sundays
    manual   — only when explicitly called
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEDULE_LABELS = {"morning", "hourly", "daily", "weekly", "manual"}

_DEFAULT_GOALS: list[dict[str, Any]] = [
    {
        "id": "morning_digest",
        "text": (
            "Summarise my last 10 unread emails, note any urgent items, "
            "and save the summary as a Google Doc titled 'Email Digest'."
        ),
        "schedules": ["morning"],
        "enabled": True,
        "tier": "notify",
    },
    {
        "id": "weekly_youtube_report",
        "text": (
            "Analyse my YouTube channels, identify the top 3 outlier videos "
            "and growth trends, then email me a brief summary."
        ),
        "schedules": ["weekly"],
        "enabled": True,
        "tier": "notify",
    },
    {
        "id": "urgent_email_watch",
        "text": (
            "Check my inbox for emails containing words like 'urgent', 'ASAP', "
            "or 'deadline'. For each one draft a polite acknowledgement reply "
            "and queue it for my approval."
        ),
        "schedules": ["hourly"],
        "enabled": True,
        "tier": "confirm",
    },
    {
        "id": "weekly_trend_research",
        "text": (
            "Search the web and YouTube for trending topics in AI tools and content creation. "
            "Append a structured summary to my 'Content Research' Google Doc."
        ),
        "schedules": ["weekly"],
        "enabled": True,
        "tier": "notify",
    },
]


class GoalLoader:
    """Load, validate, and filter goals from goals.yaml."""

    def __init__(self, path: Path | None = None) -> None:
        from jrvs.config import Config
        self._path = path or Config.AGENT_GOALS_FILE

    # ── Public API ────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        """Return all goals from goals.yaml (creates the file if missing)."""
        if not self._path.exists():
            self._write_defaults()
        return self._parse()

    def for_schedule(self, schedule: str) -> list[dict[str, Any]]:
        """Return enabled goals matching *schedule*."""
        all_goals = self.load()
        return [
            g for g in all_goals
            if g.get("enabled", True) and schedule in g.get("schedules", [])
        ]

    def get(self, goal_id: str) -> dict[str, Any] | None:
        """Return a single goal by ID, or None."""
        for g in self.load():
            if g["id"] == goal_id:
                return g
        return None

    def all(self) -> list[dict[str, Any]]:
        """Return all goals (enabled or not)."""
        return self.load()

    # ── Internals ─────────────────────────────────────────────────────

    def _parse(self) -> list[dict[str, Any]]:
        try:
            import yaml  # type: ignore
        except ImportError:
            log.warning("PyYAML not installed — using default goals only")
            return _DEFAULT_GOALS

        try:
            with open(self._path) as f:
                data = yaml.safe_load(f) or {}
            goals = data.get("goals", [])
            validated = []
            for g in goals:
                # Accept both "goal" and "text" as the goal description key
                if g.get("goal") and not g.get("text"):
                    g["text"] = g["goal"]
                elif g.get("text") and not g.get("goal"):
                    g["goal"] = g["text"]
                if not g.get("id") or not (g.get("text") or g.get("goal")):
                    log.warning("Skipping goal with missing id/text: %s", g)
                    continue
                g.setdefault("schedules", ["manual"])
                g.setdefault("enabled", True)
                g.setdefault("tier", "notify")
                validated.append(g)
            return validated
        except Exception as exc:
            log.error("Failed to parse goals.yaml: %s", exc)
            return _DEFAULT_GOALS

    def _write_defaults(self) -> None:
        """Write a starter goals.yaml so the user has something to edit."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import yaml  # type: ignore
            with open(self._path, "w") as f:
                yaml.dump(
                    {"goals": _DEFAULT_GOALS},
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            log.info("Created default goals.yaml at %s", self._path)
        except ImportError:
            # Write raw YAML without the library
            lines = ["goals:\n"]
            for g in _DEFAULT_GOALS:
                lines.append(f"  - id: {g['id']}\n")
                lines.append(f"    text: \"{g['text']}\"\n")
                lines.append(f"    schedules: {g['schedules']}\n")
                lines.append(f"    enabled: {str(g['enabled']).lower()}\n")
                lines.append(f"    tier: {g['tier']}\n\n")
            with open(self._path, "w") as f:
                f.writelines(lines)
