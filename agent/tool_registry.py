"""
JARVIS Tool Registry — decorator-based self-registering tool catalogue.

Usage:
    from agent.tool_registry import jarvis_tool, tool_registry, AUTO, NOTIFY, CONFIRM

    @jarvis_tool(name="gmail_send", tier=CONFIRM, desc="Send an email")
    async def gmail_send(to: str, subject: str, body: str) -> dict:
        ...

Import agent.tools to register all built-in tools before using the registry.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# ── Tier constants ────────────────────────────────────────────────────────────
AUTO    = "auto"
NOTIFY  = "notify"
CONFIRM = "confirm"
BLOCKED = "blocked"

TIER_ORDER: dict[str, int] = {AUTO: 0, NOTIFY: 1, CONFIRM: 2, BLOCKED: 3}


def max_tier(a: str, b: str) -> str:
    """Return the more restrictive of two tier strings."""
    return a if TIER_ORDER.get(a, 2) >= TIER_ORDER.get(b, 2) else b


class ToolSpec:
    """Metadata and callable for a registered tool."""
    __slots__ = ("name", "tier", "desc", "fn")

    def __init__(self, name: str, tier: str, desc: str, fn: Callable) -> None:
        self.name = name
        self.tier = tier
        self.desc = desc
        self.fn   = fn


class ToolRegistry:
    """Global registry of all JARVIS tools."""

    _tools: dict[str, ToolSpec] = {}

    @classmethod
    def register(cls, name: str, tier: str, desc: str) -> Callable:
        """
        Decorator factory. Registers a tool function under name.

        Example::

            @tool_registry.register(name="docs_create", tier=NOTIFY, desc="Create a Google Doc")
            async def docs_create(title: str, content: str = "") -> dict:
                ...
        """
        def decorator(fn: Callable) -> Callable:
            cls._tools[name] = ToolSpec(name=name, tier=tier, desc=desc, fn=fn)
            log.debug("Registered tool: %s [%s]", name, tier.upper())
            return fn
        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[ToolSpec]:
        return cls._tools.get(name)

    @classmethod
    def all(cls) -> list[ToolSpec]:
        return list(cls._tools.values())

    @classmethod
    def names(cls) -> set[str]:
        return set(cls._tools.keys())

    @classmethod
    def catalogue_for_prompt(cls, exclude: "set[str] | None" = None) -> str:
        """Return a formatted string of all tools for LLM system prompts.

        Args:
            exclude: optional set of tool name prefixes or exact names to omit.
        """
        lines = []
        for spec in sorted(cls._tools.values(), key=lambda s: (TIER_ORDER[s.tier], s.name)):
            if exclude and any(spec.name.startswith(p) or spec.name == p for p in exclude):
                continue
            lines.append(f"  {spec.name} [{spec.tier.upper()}] — {spec.desc}")
        return "\n".join(lines)

    @classmethod
    def tier_of(cls, name: str) -> str:
        """Return the tier for a tool, defaulting to CONFIRM for unknown tools."""
        spec = cls._tools.get(name)
        return spec.tier if spec else CONFIRM

    @classmethod
    async def call(cls, name: str, args: dict[str, Any]) -> Any:
        """Execute a registered tool by name. Raises ValueError if not found."""
        spec = cls._tools.get(name)
        if spec is None:
            raise ValueError(f"Unknown tool: {name!r}")
        return await spec.fn(**args)


# Module-level singleton
tool_registry = ToolRegistry()


def jarvis_tool(name: str, tier: str, desc: str) -> Callable:
    """Convenience alias for ToolRegistry.register."""
    return ToolRegistry.register(name=name, tier=tier, desc=desc)
