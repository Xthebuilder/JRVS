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

import inspect
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


def _type_name(param: inspect.Parameter) -> str:
    """Render ':type' for a parameter, or '' when it has no simple annotation.

    Names alone are not enough: a planner told only that code_analyze takes
    'analysis_type' will happily send a list, and the tool then does a dict
    lookup on it and dies with "unhashable type: 'list'". Advertising ':str'
    is far cheaper than validating every argument's shape at call time.
    """
    ann = param.annotation
    if ann is inspect.Parameter.empty:
        return ""
    # Modules using `from __future__ import annotations` (agent/tools.py does)
    # hand back the annotation as a string rather than the type object, so both
    # forms have to be handled.
    name = ann if isinstance(ann, str) else getattr(ann, "__name__", None)
    # Only emit short, unambiguous builtin names — anything else (Optional[...],
    # unions, custom classes) costs prompt tokens without guiding the model.
    if name in {"str", "int", "float", "bool", "list", "dict"}:
        return f":{name}"
    return ""


def _describe_params(fn: Callable) -> tuple[str, frozenset[str], bool, frozenset[str]]:
    """Render a tool's call signature for the prompt, plus its accepted names.

    Returns (signature_text, accepted_names, accepts_any_kwarg, required_names).
    Required
    parameters are listed bare, optional ones get a trailing '?', and **kwargs
    renders as '**name'. The text is deliberately terse: OLLAMA_NUM_CTX is as
    low as 4096 on this box, so the catalogue competes with the rest of the
    prompt for room.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        # Un-introspectable (C builtin, exotic wrapper): advertise nothing and
        # let the call through rather than blocking a working tool.
        return "", frozenset(), True, frozenset()

    rendered: list[str] = []
    accepted: set[str] = set()
    required: set[str] = set()
    var_kw = False
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            rendered.append(f"**{name}")
            var_kw = True
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        accepted.add(name)
        optional = param.default is not inspect.Parameter.empty
        if not optional:
            required.add(name)
        rendered.append(f"{name}?{_type_name(param)}" if optional
                        else f"{name}{_type_name(param)}")

    text = "(" + ", ".join(rendered) + ")" if rendered else "()"
    return text, frozenset(accepted), var_kw, frozenset(required)


class ToolSpec:
    """Metadata and callable for a registered tool."""
    __slots__ = ("name", "tier", "desc", "fn", "params_text", "accepted_params",
                 "accepts_any_kwarg", "required_params")

    def __init__(self, name: str, tier: str, desc: str, fn: Callable) -> None:
        self.name = name
        self.tier = tier
        self.desc = desc
        self.fn   = fn
        # Computed once at registration — the catalogue is rebuilt on every
        # planner call, so per-prompt introspection would be wasted work.
        (self.params_text,
         self.accepted_params,
         self.accepts_any_kwarg,
         self.required_params) = _describe_params(fn)


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
            # The signature is not decoration: call() dispatches with fn(**args),
            # so a guessed parameter name is a hard TypeError. Without this the
            # planner has to infer argument names from the description alone.
            lines.append(
                f"  {spec.name}{spec.params_text} [{spec.tier.upper()}] — {spec.desc}"
            )
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

        # Surface the accepted parameter names on a mismatch. AgentLoop retries
        # failed steps, but a bare "unexpected keyword argument 'file_path'"
        # gives it nothing to correct toward, so it just guesses again.
        unknown = set(args) - spec.accepted_params
        if unknown and not spec.accepts_any_kwarg:
            raise TypeError(
                f"{name}() got unexpected argument(s) {sorted(unknown)}; "
                f"accepted parameters are {sorted(spec.accepted_params)}"
            )

        missing = spec.required_params - set(args)
        if missing:
            raise TypeError(
                f"{name}() is missing required argument(s) {sorted(missing)}; "
                f"accepted parameters are {sorted(spec.accepted_params)}"
            )

        return await spec.fn(**args)


# Module-level singleton
tool_registry = ToolRegistry()


def jarvis_tool(name: str, tier: str, desc: str) -> Callable:
    """Convenience alias for ToolRegistry.register."""
    return ToolRegistry.register(name=name, tier=tier, desc=desc)
