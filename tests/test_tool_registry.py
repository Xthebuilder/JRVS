"""
Unit tests for the tool registry's prompt catalogue and argument dispatch.

The catalogue is the only thing telling the planner what arguments a tool
takes, and call() dispatches with fn(**args) — so a name the catalogue omits
becomes a hard TypeError at execution time.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.tool_registry import (
    AUTO,
    NOTIFY,
    ToolRegistry,
    ToolSpec,
    _describe_params,
)


def _spec(fn, name="sample", tier=AUTO, desc="a sample tool") -> ToolSpec:
    return ToolSpec(name=name, tier=tier, desc=desc, fn=fn)


class TestDescribeParams:
    def test_required_params_render_bare(self):
        async def fn(to: str, subject: str): ...
        text, accepted, var_kw, _req = _describe_params(fn)
        assert text == "(to:str, subject:str)"
        assert accepted == frozenset({"to", "subject"})
        assert var_kw is False

    def test_optional_params_get_a_question_mark(self):
        async def fn(query: str, max_results: int = 10): ...
        text, accepted, _, _req = _describe_params(fn)
        assert text == "(query:str, max_results?:int)"
        assert accepted == frozenset({"query", "max_results"})

    def test_no_params_renders_empty_parens(self):
        async def fn(): ...
        text, accepted, var_kw, _req = _describe_params(fn)
        assert text == "()"
        assert accepted == frozenset()
        assert var_kw is False

    def test_var_keyword_is_flagged_and_rendered(self):
        async def fn(event_id: str, **fields): ...
        text, accepted, var_kw, _req = _describe_params(fn)
        assert text == "(event_id:str, **fields)"
        assert var_kw is True
        # The **kwargs name itself is not a real parameter to match against.
        assert accepted == frozenset({"event_id"})

    def test_var_positional_is_omitted(self):
        async def fn(a: str, *rest): ...
        text, _, _, _req = _describe_params(fn)
        assert text == "(a:str)"

    def test_unannotated_param_renders_without_a_type(self):
        async def fn(a, b: int = 1): ...
        text, _, _, _req = _describe_params(fn)
        assert text == "(a, b?:int)"


class TestTypeAnnotations:
    """
    Types matter as much as names. code_analyze does a dict lookup on its
    analysis_type argument, so a planner that sends a list instead of a string
    crashes it with "unhashable type: 'list'".
    """

    def test_string_annotations_are_resolved(self):
        """
        Modules using `from __future__ import annotations` — agent/tools.py
        does — hand back annotations as strings, not type objects.
        """
        async def fn(code: str, count: int = 1): ...
        fn.__annotations__ = {"code": "str", "count": "int"}
        text, _, _, _req = _describe_params(fn)
        assert text == "(code:str, count?:int)"

    @pytest.mark.parametrize("annotation", ["str", "int", "float", "bool", "list", "dict"])
    def test_builtin_types_are_emitted(self, annotation):
        async def fn(x: str = ""): ...
        fn.__annotations__ = {"x": annotation}
        text, _, _, _req = _describe_params(fn)
        assert text == f"(x?:{annotation})"

    def test_complex_annotations_are_omitted_to_save_tokens(self):
        async def fn(x: str = ""): ...
        fn.__annotations__ = {"x": "Optional[dict[str, Any]]"}
        text, _, _, _req = _describe_params(fn)
        assert text == "(x?)"


class TestCatalogueForPrompt:
    def test_line_includes_signature_tier_and_desc(self):
        async def gmail_send(to: str, subject: str, body: str = ""): ...

        registry = type("R", (ToolRegistry,), {"_tools": {}})
        registry._tools["gmail_send"] = _spec(
            gmail_send, name="gmail_send", tier=NOTIFY, desc="Send an email"
        )

        line = registry.catalogue_for_prompt().strip()
        assert line == "gmail_send(to:str, subject:str, body?:str) [NOTIFY] — Send an email"

    def test_exclude_filters_by_prefix(self):
        async def a(): ...
        async def b(): ...

        registry = type("R", (ToolRegistry,), {"_tools": {}})
        registry._tools["gmail_send"] = _spec(a, name="gmail_send")
        registry._tools["file_read"] = _spec(b, name="file_read")

        out = registry.catalogue_for_prompt(exclude={"gmail_"})
        assert "file_read" in out
        assert "gmail_send" not in out


class TestCallArgumentValidation:
    @pytest.fixture
    def registry(self):
        async def file_read(filename: str = "", path: str = ""):
            return f"read:{filename or path}"

        async def calendar_update(event_id: str, **fields):
            return {"event_id": event_id, "fields": fields}

        reg = type("R", (ToolRegistry,), {"_tools": {}})
        reg._tools["file_read"] = _spec(file_read, name="file_read")
        reg._tools["calendar_update"] = _spec(calendar_update, name="calendar_update")
        return reg

    async def test_correct_args_dispatch(self, registry):
        assert await registry.call("file_read", {"filename": "x.txt"}) == "read:x.txt"

    async def test_wrong_arg_names_the_accepted_parameters(self, registry):
        """
        Regression: the planner guessed 'file_path' (the MCP filesystem
        convention) and got a bare "unexpected keyword argument", which gave
        AgentLoop's retry nothing to correct toward.
        """
        with pytest.raises(TypeError) as exc:
            await registry.call("file_read", {"file_path": "/tmp/x"})

        msg = str(exc.value)
        assert "file_path" in msg
        assert "filename" in msg and "path" in msg

    async def test_var_kwargs_tool_accepts_arbitrary_names(self, registry):
        """A **kwargs tool must not be rejected by the strict check."""
        out = await registry.call(
            "calendar_update", {"event_id": "e1", "summary": "New title"}
        )
        assert out == {"event_id": "e1", "fields": {"summary": "New title"}}

    async def test_unknown_tool_raises_value_error(self, registry):
        with pytest.raises(ValueError):
            await registry.call("nope", {})


class TestMissingRequiredArgs:
    @pytest.fixture
    def registry(self):
        async def code_fix(code: str, error_message: str = "", language: str = "python"):
            return f"fixed:{code}"

        reg = type("R", (ToolRegistry,), {"_tools": {}})
        reg._tools["code_fix"] = _spec(code_fix, name="code_fix")
        return reg

    async def test_missing_required_arg_names_what_is_needed(self, registry):
        """
        Regression: the planner called code_fix() with no 'code', and Python's
        "missing 1 required positional argument" told the retry nothing about
        what the tool actually accepts.
        """
        with pytest.raises(TypeError) as exc:
            await registry.call("code_fix", {"language": "python"})

        msg = str(exc.value)
        assert "code" in msg
        assert "error_message" in msg and "language" in msg

    async def test_supplying_required_arg_succeeds(self, registry):
        assert await registry.call("code_fix", {"code": "x=1"}) == "fixed:x=1"
