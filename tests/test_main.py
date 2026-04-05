"""
Unit tests for main.py

Tests CLI argument parsing, dependency checking, and connection checks.
All network calls and subprocesses are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import argparse

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import parse_arguments, check_dependencies, check_ollama_connection, check_lmstudio_connection


# ---------------------------------------------------------------------------
# Argument Parsing
# ---------------------------------------------------------------------------

class TestParseArguments:
    def test_defaults(self):
        args = parse_arguments([])
        assert args.debug is False
        assert args.no_banner is False
        assert args.use_lmstudio is False

    def test_debug_flag(self):
        args = parse_arguments(["--debug"])
        assert args.debug is True

    def test_no_banner_flag(self):
        args = parse_arguments(["--no-banner"])
        assert args.no_banner is True

    def test_model_flag(self):
        args = parse_arguments(["--model", "llama3"])
        assert args.model == "llama3"

    def test_ollama_url_flag(self):
        args = parse_arguments(["--ollama-url", "http://remote:11434"])
        assert args.ollama_url == "http://remote:11434"

    def test_use_lmstudio_flag(self):
        args = parse_arguments(["--use-lmstudio"])
        assert args.use_lmstudio is True

    def test_lmstudio_url_flag(self):
        args = parse_arguments(["--lmstudio-url", "http://localhost:1234/v1"])
        assert args.lmstudio_url == "http://localhost:1234/v1"

    def test_version_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_arguments(["--version"])

    def test_unknown_arg_raises(self):
        with pytest.raises(SystemExit):
            parse_arguments(["--totally-unknown-flag"])


# ---------------------------------------------------------------------------
# Dependency Check
# ---------------------------------------------------------------------------

class TestCheckDependencies:
    def test_returns_bool(self):
        result = check_dependencies()
        assert isinstance(result, bool)

    def test_returns_true_when_core_deps_present(self):
        # rich and beautifulsoup4 are in the venv; should return True
        with patch.dict("sys.modules", {}):
            result = check_dependencies()
        assert result is True


# ---------------------------------------------------------------------------
# Connection Checks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckOllamaConnection:
    async def test_returns_true_on_200(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=cm)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await check_ollama_connection("http://localhost:11434")

        assert result is True

    async def test_returns_false_on_connection_error(self):
        with patch("aiohttp.ClientSession") as MockSession:
            instance = MagicMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("refused"))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.get = MagicMock(return_value=cm)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockSession.return_value = instance
            result = await check_ollama_connection("http://localhost:11434")

        assert result is False


@pytest.mark.asyncio
class TestCheckLMStudioConnection:
    async def test_returns_true_on_200(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=cm)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await check_lmstudio_connection("http://localhost:1234/v1")

        assert result is True

    async def test_returns_false_on_error(self):
        with patch("aiohttp.ClientSession") as MockSession:
            instance = MagicMock()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=Exception("no lmstudio"))
            cm.__aexit__ = AsyncMock(return_value=False)
            instance.get = MagicMock(return_value=cm)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockSession.return_value = instance
            result = await check_lmstudio_connection("http://localhost:1234/v1")

        assert result is False
