"""
JARVIS fixed role registry — maps sub-agent roles onto existing tool
clusters (agent/tools.py), for the lead-agent + sub-agent-team architecture
(agent/lead.py). Roles are static, not invented dynamically per goal.

Import agent.tools before calling tools_for_role()/role_catalogue_for_prompt()
so all @jarvis_tool decorators have registered — same requirement as
tool_registry itself.
"""
from __future__ import annotations

from agent.tool_registry import tool_registry

ROLES: dict[str, dict] = {
    "ops": {
        "prefixes": {"gmail_", "docs_", "sheets_", "calendar_", "nextcloud_", "file_"},
        "desc": "Email, documents, spreadsheets, calendar (Google Workspace + Nextcloud), local sandboxed files",
    },
    "research": {
        "prefixes": {"web_search", "youtube_"},
        "desc": "Web search and YouTube channel/video analytics",
    },
    "comms": {
        "prefixes": {"marketing_", "image_gen_"},
        "desc": "Marketing copy drafts and image generation",
    },
    "coder": {
        "prefixes": {"code_"},
        "desc": "Code generation, analysis, refactoring, testing, and execution",
    },
}


def tools_for_role(role: str) -> "set[str]":
    """Resolve a role's prefixes against currently registered tool names."""
    spec = ROLES.get(role)
    if not spec:
        return set()
    prefixes = spec["prefixes"]
    return {
        name for name in tool_registry.names()
        if any(name.startswith(p) or name == p for p in prefixes)
    }


def role_catalogue_for_prompt() -> str:
    """
    Short role-name + one-line-description listing for the lead's
    decomposition prompt — deliberately much smaller than the full tool
    catalogue each role engine sees when planning its own steps, since the
    lead only needs to know which domain a subtask belongs to, not the
    individual tools within it.
    """
    lines = [f"  {name} — {spec['desc']}" for name, spec in ROLES.items()]
    return "\n".join(lines)
