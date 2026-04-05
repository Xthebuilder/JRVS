"""
Unit tests for mcp_gateway/coding_agent.py (JARCORE class)

File I/O and LLM calls are mocked — no real filesystem writes or
model inference.
"""

import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
import os

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_gateway.coding_agent import JARCORE, SecurityError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jarcore(tmp_path=None):
    ws = str(tmp_path) if tmp_path else tempfile.mkdtemp()
    jc = JARCORE(workspace_root=ws)
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value=None)
    jc._llm_client = mock_llm
    return jc


def _llm_response(data: dict) -> str:
    return f"```json\n{json.dumps(data)}\n```"


# ---------------------------------------------------------------------------
# Path Validation
# ---------------------------------------------------------------------------

class TestValidatePath:
    def test_valid_path_within_workspace(self, tmp_path):
        jc = _jarcore(tmp_path)
        p = jc._validate_path("script.py")
        assert p.parent == Path(str(tmp_path))

    def test_rejects_path_traversal(self, tmp_path):
        jc = _jarcore(tmp_path)
        with pytest.raises(SecurityError):
            jc._validate_path("../../../etc/passwd")

    def test_rejects_dotenv(self, tmp_path):
        jc = _jarcore(tmp_path)
        with pytest.raises(SecurityError):
            jc._validate_path(".env")

    def test_rejects_git_dir(self, tmp_path):
        jc = _jarcore(tmp_path)
        with pytest.raises(SecurityError):
            jc._validate_path(".git/config")

    def test_nested_path_allowed(self, tmp_path):
        jc = _jarcore(tmp_path)
        p = jc._validate_path("src/utils/helper.py")
        assert "helper.py" in str(p)


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:
    def test_direct_json_string(self, tmp_path):
        jc = _jarcore(tmp_path)
        data, err = jc._extract_json('{"key": "value"}')
        assert data == {"key": "value"}
        assert err is None

    def test_json_in_code_block(self, tmp_path):
        jc = _jarcore(tmp_path)
        data, err = jc._extract_json('```json\n{"a": 1}\n```')
        assert data == {"a": 1}

    def test_returns_none_for_invalid_json(self, tmp_path):
        jc = _jarcore(tmp_path)
        data, err = jc._extract_json("not json at all")
        assert data is None
        assert err is not None

    def test_extracts_nested_json(self, tmp_path):
        jc = _jarcore(tmp_path)
        text = 'Here is the result: {"code": "print(1)", "explanation": "simple"}'
        data, err = jc._extract_json(text)
        assert data is not None
        assert data["code"] == "print(1)"


# ---------------------------------------------------------------------------
# File Operations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReadFile:
    async def test_read_existing_file(self, tmp_path):
        (tmp_path / "hello.py").write_text("print('hi')")
        jc = _jarcore(tmp_path)
        result = await jc.read_file("hello.py")
        assert result["exists"] is True
        assert "print" in result["content"]

    async def test_read_nonexistent_file(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.read_file("ghost.py")
        assert result["exists"] is False
        assert "error" in result

    async def test_read_returns_metadata(self, tmp_path):
        (tmp_path / "f.py").write_text("x = 1\ny = 2\n")
        jc = _jarcore(tmp_path)
        result = await jc.read_file("f.py")
        assert result["lines"] == 2
        assert result["language"] == "python"

    async def test_read_path_traversal_blocked(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.read_file("../../etc/passwd")
        assert "error" in result


@pytest.mark.asyncio
class TestWriteFile:
    async def test_write_creates_file(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.write_file("new.py", "print('hello')", backup=False)
        assert result["success"] is True
        assert (tmp_path / "new.py").exists()

    async def test_write_returns_bytes_written(self, tmp_path):
        jc = _jarcore(tmp_path)
        content = "x = 42\n"
        result = await jc.write_file("x.py", content, backup=False)
        assert result["bytes_written"] == len(content.encode())

    async def test_write_creates_dirs(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.write_file("sub/dir/file.py", "pass", create_dirs=True, backup=False)
        assert result["success"] is True
        assert (tmp_path / "sub/dir/file.py").exists()

    async def test_write_creates_backup(self, tmp_path):
        (tmp_path / "existing.py").write_text("old content")
        jc = _jarcore(tmp_path)
        await jc.write_file("existing.py", "new content", backup=True)
        backups = list(tmp_path.glob("existing.py.bak*"))
        assert len(backups) >= 1

    async def test_write_path_traversal_blocked(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.write_file("../../danger.py", "evil", backup=False)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Code Generation (mocked LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGenerateCode:
    async def test_returns_dict_with_code_key(self, tmp_path):
        jc = _jarcore(tmp_path)
        resp = _llm_response({"code": "def fib(n): pass", "explanation": "simple"})
        jc._llm_client.generate = AsyncMock(return_value=resp)
        with patch("mcp_gateway.coding_agent.rag_retriever") as mock_rag:
            mock_rag.get_context = AsyncMock(return_value="")
            result = await jc.generate_code("fibonacci function", "python")
        assert "code" in result

    async def test_error_returned_when_llm_fails(self, tmp_path):
        jc = _jarcore(tmp_path)
        jc._llm_client.generate = AsyncMock(return_value=None)
        with patch("mcp_gateway.coding_agent.rag_retriever") as mock_rag:
            mock_rag.get_context = AsyncMock(return_value="")
            result = await jc.generate_code("anything")
        assert "error" in result


# ---------------------------------------------------------------------------
# Explain Code (mocked LLM)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExplainCode:
    async def test_returns_string_explanation(self, tmp_path):
        jc = _jarcore(tmp_path)
        jc._llm_client.generate = AsyncMock(return_value="This function adds two numbers.")
        result = await jc.explain_code("def add(a, b): return a+b", "python")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_returns_error_string_on_llm_failure(self, tmp_path):
        jc = _jarcore(tmp_path)
        jc._llm_client.generate = AsyncMock(return_value=None)
        result = await jc.explain_code("code", "python")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Edit History
# ---------------------------------------------------------------------------

class TestEditHistory:
    def test_history_starts_empty(self, tmp_path):
        jc = _jarcore(tmp_path)
        assert jc.get_edit_history() == []

    @pytest.mark.asyncio
    async def test_history_populated_after_write(self, tmp_path):
        jc = _jarcore(tmp_path)
        await jc.write_file("test.py", "pass", backup=False)
        history = jc.get_edit_history()
        assert len(history) >= 1

    def test_history_limit_respected(self, tmp_path):
        jc = _jarcore(tmp_path)
        # max_history defaults to 1000; just verify get_edit_history(limit=) works
        history = jc.get_edit_history(limit=5)
        assert len(history) <= 5


# ---------------------------------------------------------------------------
# Code Execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecuteCode:
    async def test_execute_simple_python(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.execute_code("print('hello')", language="python", timeout=10)
        assert result["success"] is True
        assert "hello" in result.get("stdout", "")

    async def test_execute_returns_exit_code(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.execute_code("x = 1", language="python", timeout=10)
        assert "exit_code" in result

    async def test_execute_unsupported_language(self, tmp_path):
        jc = _jarcore(tmp_path)
        result = await jc.execute_code("code", language="cobol", timeout=10)
        assert result.get("success") is False or "error" in result
