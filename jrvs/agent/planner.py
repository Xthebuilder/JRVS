"""
JRVS Agent — LLM-powered multi-step planner.

Given a goal (natural-language string) and optional memory/context,
the planner asks Ollama to break the goal into an ordered list of
tool calls that JRVS can execute.

Each step in the plan has:
    {
        "step":   int,          # 1-based execution order
        "tool":   str,          # matches agent/executor tool name
        "args":   dict,         # tool arguments
        "tier":   str,          # auto / notify / confirm / blocked
        "reason": str,          # why this step is needed
    }
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# ── Tool catalogue visible to the planner ───────────────────────────────────
# Kept intentionally brief — just name, what it does, tier, and key args.

PLANNER_TOOLS: list[dict[str, Any]] = [
    # ── Read (AUTO) ─────────────────────────────────────────────────────
    {"name": "gmail_list",              "tier": "auto",    "desc": "List recent inbox emails"},
    {"name": "gmail_search",            "tier": "auto",    "desc": "Search Gmail with query syntax"},
    {"name": "gmail_read",              "tier": "auto",    "desc": "Read full email body by ID"},
    {"name": "gmail_labels",            "tier": "auto",    "desc": "List Gmail labels"},
    {"name": "docs_list",               "tier": "auto",    "desc": "List recent Google Docs"},
    {"name": "docs_read",               "tier": "auto",    "desc": "Read a Google Doc by ID"},
    {"name": "docs_find",               "tier": "auto",    "desc": "Find a Google Doc by name"},
    {"name": "sheets_list",             "tier": "auto",    "desc": "List recent Google Sheets"},
    {"name": "sheets_read",             "tier": "auto",    "desc": "Read cells from a spreadsheet"},
    {"name": "sheets_find",             "tier": "auto",    "desc": "Find spreadsheet by name"},
    {"name": "sheets_info",             "tier": "auto",    "desc": "Get spreadsheet metadata"},
    {"name": "calendar_list_calendars", "tier": "auto",    "desc": "List all calendars"},
    {"name": "calendar_events",         "tier": "auto",    "desc": "List upcoming calendar events"},
    {"name": "calendar_find",           "tier": "auto",    "desc": "Search calendar events"},
    {"name": "youtube_analyze",         "tier": "auto",    "desc": "Analyse a YouTube channel's performance"},
    {"name": "youtube_outliers",        "tier": "auto",    "desc": "Find viral outlier videos for a channel"},
    {"name": "youtube_growth",          "tier": "auto",    "desc": "Get growth trend for a channel"},
    {"name": "web_search",              "tier": "auto",    "desc": "Brave + YouTube web search with semantic RAG"},
    # ── Write (NOTIFY) ───────────────────────────────────────────────────
    {"name": "docs_create",             "tier": "notify",  "desc": "Create a new Google Doc"},
    {"name": "docs_append",             "tier": "notify",  "desc": "Append text to a Google Doc"},
    {"name": "docs_replace",            "tier": "notify",  "desc": "Find-and-replace in a Google Doc"},
    {"name": "sheets_write",            "tier": "notify",  "desc": "Write values to a spreadsheet range"},
    {"name": "sheets_append",           "tier": "notify",  "desc": "Append rows to a spreadsheet"},
    {"name": "sheets_create",           "tier": "notify",  "desc": "Create a new Google Sheets spreadsheet"},
    {"name": "sheets_clear",            "tier": "notify",  "desc": "Clear a spreadsheet range"},
    {"name": "calendar_create",         "tier": "notify",  "desc": "Create a calendar event"},
    {"name": "calendar_update",         "tier": "notify",  "desc": "Update a calendar event"},
    # ── Send / Delete (CONFIRM) ───────────────────────────────────────────
    {"name": "gmail_send",              "tier": "confirm", "desc": "Send an email"},
    {"name": "gmail_reply",             "tier": "confirm", "desc": "Reply to an email thread"},
    {"name": "calendar_delete",         "tier": "confirm", "desc": "Delete a calendar event"},
]

_TOOL_NAMES = {t["name"] for t in PLANNER_TOOLS}
_TOOL_TIERS = {t["name"]: t["tier"] for t in PLANNER_TOOLS}

_CATALOGUE = "\n".join(
    f"  {t['name']} [{t['tier'].upper()}] — {t['desc']}"
    for t in PLANNER_TOOLS
)

_SYSTEM_PROMPT = f"""You are JRVS, an autonomous AI assistant.

Your job is to break a user's goal into an ordered list of tool calls.

Available tools (name [TIER] — description):
{_CATALOGUE}

TIER meanings:
  AUTO    — safe to execute silently
  NOTIFY  — executes automatically, but owner is notified by email
  CONFIRM — must wait for owner approval before executing
  BLOCKED — never execute autonomously

Rules:
1. Return ONLY a JSON array of steps. No explanation.
2. Each step: {{"step": int, "tool": str, "args": {{}}, "tier": str, "reason": str}}
3. Steps must be in logical execution order (reads before writes).
4. Use results from earlier read steps to fill args for later write/send steps
   — mark those with a placeholder like "<result_from_step_1>".
5. Keep plans concise — 10 steps max.
6. If a goal requires sending email, tier MUST be "confirm".
7. NEVER invent tools not in the list.
"""


class Planner:
    """Ask the LLM to decompose a goal into an executable plan."""

    def __init__(self, ollama=None) -> None:
        from jrvs.llm.ollama_client import OllamaClient
        self._llm = ollama or OllamaClient()

    def plan(
        self,
        goal_text: str,
        memory: dict[str, str] | None = None,
        max_steps: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return an ordered list of step dicts for *goal_text*.

        Parameters
        ----------
        goal_text : The natural-language goal to plan for.
        memory    : Key/value pairs from previous runs (context injection).
        max_steps : Cap on plan length (default from Config).
        """
        from jrvs.config import Config
        max_steps = max_steps or Config.AGENT_MAX_STEPS

        context = ""
        if memory:
            parts = [f"  {k}: {v}" for k, v in list(memory.items())[:10]]
            context = "\nMemory from previous runs:\n" + "\n".join(parts) + "\n"

        user_msg = (
            f"{context}"
            f"Goal: {goal_text}\n\n"
            f"Produce an execution plan (max {max_steps} steps) as a JSON array."
        )

        try:
            raw = self._llm.chat(messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ])
            steps = _parse_json(raw)
            if not isinstance(steps, list):
                steps = [steps]
            return self._validate(steps, max_steps)
        except Exception as exc:
            log.error("Planning failed for goal '%s': %s", goal_text[:60], exc)
            return []

    def replan(
        self,
        goal_text: str,
        failed_step: dict[str, Any],
        error: str,
        remaining: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Ask the LLM to recover from a failed step and produce a new tail plan."""
        user_msg = (
            f"Goal: {goal_text}\n\n"
            f"Step {failed_step.get('step')} ({failed_step.get('tool')}) failed "
            f"with error: {error}\n\n"
            f"Remaining planned steps were:\n{json.dumps(remaining, indent=2)}\n\n"
            "Revise the remaining steps to recover from this failure. "
            "Return a JSON array of revised steps only."
        )
        try:
            raw = self._llm.chat(messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ])
            steps = _parse_json(raw)
            if not isinstance(steps, list):
                steps = [steps]
            return self._validate(steps, 10)
        except Exception as exc:
            log.error("Replan failed: %s", exc)
            return remaining  # fall back to original remaining steps

    # ── Helpers ───────────────────────────────────────────────────────

    def _validate(
        self, steps: list[dict[str, Any]], max_steps: int
    ) -> list[dict[str, Any]]:
        """Sanitise and cap the plan."""
        valid = []
        for i, s in enumerate(steps[:max_steps]):
            tool = s.get("tool", "")
            if isinstance(tool, list):
                tool = tool[0] if tool else ""
            if tool not in _TOOL_NAMES:
                log.warning("Planner chose unknown tool '%s' — skipping", tool)
                continue
            # Enforce tier from our registry (don't trust LLM tier)
            s["tool"] = tool
            s["tier"] = _TOOL_TIERS.get(tool, "confirm")
            s.setdefault("step", i + 1)
            s.setdefault("args", {})
            s.setdefault("reason", "")
            valid.append(s)
        return valid


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"(\[[\s\S]+\]|\{[\s\S]+\})", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No JSON found in planner response:\n{text[:300]}")
