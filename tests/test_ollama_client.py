"""
Unit tests for llm/ollama_client.py

All HTTP calls are mocked — no real Ollama server required.
"""

import sys
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm.ollama_client import OllamaClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(base_url="http://localhost:11434"):
    return OllamaClient(base_url=base_url)


def _mock_response(data, status=200):
    """Build a minimal mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=data)
    resp.text = AsyncMock(return_value=json.dumps(data))
    return resp


def _mock_session(resp):
    """Build a minimal mock ClientSession context manager."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=cm)
    session.post = MagicMock(return_value=cm)
    session.close = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestOllamaClientInit:
    def test_base_url_stored(self):
        client = _make_client("http://myhost:11434")
        assert "myhost" in client.base_url

    def test_session_initially_none(self):
        client = _make_client()
        assert client.session is None

    def test_default_model_set(self):
        client = _make_client()
        assert isinstance(client.current_model, str)


# ---------------------------------------------------------------------------
# Model Discovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDiscoverModels:
    async def test_returns_model_names_from_api(self):
        client = _make_client()
        tags_data = {"models": [{"name": "llama3"}, {"name": "mistral"}]}
        resp = _mock_response(tags_data)
        session = _mock_session(resp)

        with patch.object(client, "_get_session", AsyncMock(return_value=session)):
            models = await client.discover_models()

        assert "llama3" in models
        assert "mistral" in models

    async def test_returns_empty_on_connection_error(self):
        client = _make_client()
        session = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("refused"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=cm)

        with patch.object(client, "_get_session", AsyncMock(return_value=session)):
            models = await client.discover_models()

        assert models == []

    async def test_uses_cached_models_within_interval(self):
        client = _make_client()
        client._available_models = ["cached-model"]
        client._last_model_check = __import__("time").time()  # just now

        models = await client.discover_models()
        assert "cached-model" in models


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_simple_user_message(self):
        client = _make_client()
        msgs = client._build_messages("hello")
        # Should have system + user
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert msgs[-1]["content"] == "hello"

    def test_context_prepended(self):
        client = _make_client()
        msgs = client._build_messages("question", context="some docs")
        combined = " ".join(m["content"] for m in msgs)
        assert "some docs" in combined

    def test_conversation_history_included(self):
        client = _make_client()
        history = [{"user": "hi", "assistant": "hello"}]
        msgs = client._build_messages("follow up", conversation_history=history)
        roles = [m["role"] for m in msgs]
        assert "assistant" in roles

    def test_custom_system_prompt(self):
        client = _make_client()
        msgs = client._build_messages("q", system_prompt="be brief")
        system_msgs = [m for m in msgs if m["role"] == "system"]
        assert any("brief" in m["content"] for m in system_msgs)


# ---------------------------------------------------------------------------
# Generate (non-streaming)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGenerate:
    async def test_generate_returns_content(self):
        client = _make_client()
        chat_resp = {
            "message": {"content": "The answer is 42"},
            "done": True,
        }
        resp = _mock_response(chat_resp)
        session = _mock_session(resp)

        with patch.object(client, "_get_session", AsyncMock(return_value=session)):
            result = await client.generate("What is 6×7?", stream=False)

        assert result == "The answer is 42"

    async def test_generate_returns_none_on_error(self):
        client = _make_client()
        session = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=cm)

        with patch.object(client, "_get_session", AsyncMock(return_value=session)):
            result = await client.generate("hi", stream=False)

        assert result is None


# ---------------------------------------------------------------------------
# Switch Model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSwitchModel:
    async def test_switch_to_known_model(self):
        client = _make_client()
        client._available_models = ["llama3", "mistral"]

        with patch.object(client, "generate", AsyncMock(return_value="ok")):
            success = await client.switch_model("llama3")

        assert success is True
        assert client.current_model == "llama3"

    async def test_switch_to_unknown_model_returns_false(self):
        client = _make_client()
        client._available_models = ["llama3"]

        with patch.object(client, "discover_models", AsyncMock(return_value=["llama3"])):
            success = await client.switch_model("nonexistent-model-xyz")

        assert success is False


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCleanup:
    async def test_cleanup_closes_session(self):
        client = _make_client()
        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        client.session = mock_session
        await client.cleanup()
        mock_session.close.assert_called_once()

    async def test_cleanup_with_no_session_is_safe(self):
        client = _make_client()
        client.session = None
        await client.cleanup()  # Should not raise


# ---------------------------------------------------------------------------
# set_base_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSetBaseUrl:
    async def test_updates_base_url(self):
        client = _make_client()
        await client.set_base_url("http://newhost:11434")
        assert "newhost" in client.base_url

    async def test_resets_model_cache(self):
        client = _make_client()
        client._available_models = ["old"]
        await client.set_base_url("http://other:11434")
        assert client._available_models == []
