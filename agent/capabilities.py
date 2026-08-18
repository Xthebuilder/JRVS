"""
Capability model — what JARVIS can actually do right now.

Without this the agent quietly downgrades a task it cannot perform: asked for a
calendar event with Google unauthenticated, it wrote a text file instead and
reported success. Substituting a different KIND of action is never a valid
recovery — a file is not an appointment.

Capabilities are probed cheaply and cached briefly, then rendered into the
planner prompt so the model is told what is unavailable and why, and told to
report a hard limit rather than reach for the nearest working tool.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, "Capability"]] = {}
_TTL_SECONDS = 120


class Capability:
    __slots__ = ("name", "available", "reason", "tool_prefixes", "alternative")

    def __init__(self, name: str, available: bool, reason: str,
                 tool_prefixes: tuple[str, ...], alternative: str = ""):
        self.name = name
        self.available = available
        self.reason = reason
        self.tool_prefixes = tool_prefixes
        # What DOES work for this kind of task. Without it the planner reads
        # "calendar_* unavailable" as "calendar work is impossible" and gives
        # up, even though nextcloud_* does exactly that job.
        self.alternative = alternative

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Capability({self.name}, available={self.available}, reason={self.reason!r})"


def _probe_google() -> Capability:
    creds = Path.home() / "JRVS" / "google_credentials.json"
    if creds.exists():
        return Capability("Google Workspace", True, "", ("gmail_", "docs_", "sheets_", "calendar_"))
    return Capability(
        "Google Workspace", False,
        "not authenticated — run /google-auth to connect Gmail, Docs, Sheets and Google Calendar",
        ("gmail_", "docs_", "sheets_", "calendar_"),
        alternative=(
            "for CALENDAR work use the nextcloud_* tools, which are available and "
            "fully working — nextcloud_create puts an event on the user's calendar. "
            "For notes and documents use file_write. There is no alternative for "
            "sending email."
        ),
    )


def _probe_nextcloud() -> Capability:
    url = os.environ.get("NEXTCLOUD_URL", "").strip()
    user = os.environ.get("NEXTCLOUD_USER", "").strip()
    pw = os.environ.get("NEXTCLOUD_APP_PASSWORD", "").strip()
    if not (url and user and pw):
        return Capability(
            "Nextcloud calendar", False,
            "NEXTCLOUD_URL / NEXTCLOUD_USER / NEXTCLOUD_APP_PASSWORD are not all set",
            ("nextcloud_",),
        )
    return Capability("Nextcloud calendar", True, "", ("nextcloud_",))


def _probe_brave() -> Capability:
    if os.environ.get("BRAVE_API_KEY", "").strip():
        return Capability("Web search", True, "", ("web_search",))
    return Capability(
        "Web search", False,
        "BRAVE_API_KEY is not set (a DuckDuckGo fallback may still work)",
        ("web_search",),
    )


_PROBES = {
    "google": _probe_google,
    "nextcloud": _probe_nextcloud,
    "brave": _probe_brave,
}


def get_capabilities(force: bool = False) -> list[Capability]:
    """Probe every capability, cached for a short window."""
    now = time.time()
    out = []
    for key, probe in _PROBES.items():
        cached = _CACHE.get(key)
        if cached and not force and (now - cached[0]) < _TTL_SECONDS:
            out.append(cached[1])
            continue
        try:
            cap = probe()
        except Exception as exc:  # a probe must never break planning
            log.warning("capabilities: probe %s failed: %s", key, exc)
            cap = Capability(key, False, f"capability check failed: {exc}", ())
        _CACHE[key] = (now, cap)
        out.append(cap)
    return out


def unavailable_prefixes() -> set[str]:
    """Tool prefixes that cannot work right now."""
    return {p for cap in get_capabilities() if not cap.available for p in cap.tool_prefixes}


def describe_for_prompt() -> str:
    """Render the unavailable capabilities, with the reason, for the planner.

    Naming the reason matters: told only that a tool is missing, the model
    invents a substitute. Told *why*, it can report the limit instead.
    """
    missing = [c for c in get_capabilities() if not c.available]
    if not missing:
        return ""
    lines = ["UNAVAILABLE RIGHT NOW — these specific tools will fail, do not plan them:"]
    for cap in missing:
        tools = ", ".join(f"{p}*" if not p.endswith("*") else p for p in cap.tool_prefixes)
        lines.append(f"  {cap.name} ({tools}) — {cap.reason}")
        if cap.alternative:
            lines.append(f"    HOWEVER: {cap.alternative}")
    lines.append(
        "Use the working alternative above whenever one exists — that is the right plan, "
        "not a compromise. Only when NO tool can do the requested KIND of work should you "
        "return an empty plan: never substitute a different kind of action, because writing "
        "a file is not sending an email."
    )
    return "\n".join(lines)
