"""
Unit tests for web_server.py

Tests request model validation, get_tailscale_ip helper, and
Pydantic validators. The FastAPI app itself is not spun up
(requires too many real services), but the isolated pieces are tested.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from web_server import ChatRequest, ScrapeRequest, CodeExecuteRequest, get_tailscale_ip


# ---------------------------------------------------------------------------
# ChatRequest validation
# ---------------------------------------------------------------------------

class TestChatRequest:
    def test_valid_message(self):
        req = ChatRequest(message="Hello there")
        assert req.message == "Hello there"

    def test_message_whitespace_stripped(self):
        req = ChatRequest(message="  hi  ")
        assert req.message == "hi"

    def test_empty_message_raises(self):
        with pytest.raises(Exception):
            ChatRequest(message="")

    def test_whitespace_only_raises(self):
        with pytest.raises(Exception):
            ChatRequest(message="   ")

    def test_script_tag_removed(self):
        req = ChatRequest(message="hello <script>alert(1)</script> world")
        assert "<script>" not in req.message

    def test_session_id_optional(self):
        req = ChatRequest(message="hi")
        assert req.session_id is None

    def test_valid_session_id(self):
        req = ChatRequest(message="hi", session_id="abc-123")
        assert req.session_id == "abc-123"

    def test_invalid_session_id_raises(self):
        with pytest.raises(Exception):
            ChatRequest(message="hi", session_id="bad session id!@#")

    def test_message_too_long_raises(self):
        from core.validators import MAX_MESSAGE_LEN
        with pytest.raises(Exception):
            ChatRequest(message="x" * (MAX_MESSAGE_LEN + 1))


# ---------------------------------------------------------------------------
# ScrapeRequest validation
# ---------------------------------------------------------------------------

class TestScrapeRequest:
    def test_valid_https_url(self):
        req = ScrapeRequest(url="https://example.com/page")
        assert req.url.startswith("https://")

    def test_valid_http_url(self):
        req = ScrapeRequest(url="http://example.com")
        assert "example.com" in req.url

    def test_rejects_private_ip(self):
        with pytest.raises(Exception):
            ScrapeRequest(url="http://192.168.1.1")

    def test_rejects_localhost(self):
        with pytest.raises(Exception):
            ScrapeRequest(url="http://localhost/admin")

    def test_rejects_javascript_url(self):
        with pytest.raises(Exception):
            ScrapeRequest(url="javascript:alert(1)")

    def test_rejects_ftp(self):
        with pytest.raises(Exception):
            ScrapeRequest(url="ftp://files.example.com")

    def test_rejects_internal_ip_127(self):
        with pytest.raises(Exception):
            ScrapeRequest(url="http://127.0.0.1/")


# ---------------------------------------------------------------------------
# CodeExecuteRequest validation
# ---------------------------------------------------------------------------

class TestCodeExecuteRequest:
    def test_valid_python(self):
        req = CodeExecuteRequest(code="print('hi')", language="python")
        assert req.language == "python"
        assert req.timeout == 30

    def test_valid_bash(self):
        req = CodeExecuteRequest(code="echo hi", language="bash")
        assert req.language == "bash"

    def test_valid_javascript(self):
        req = CodeExecuteRequest(code="console.log(1)", language="javascript")
        assert req.language == "javascript"

    def test_invalid_language_raises(self):
        with pytest.raises(Exception):
            CodeExecuteRequest(code="code", language="ruby")

    def test_custom_timeout(self):
        req = CodeExecuteRequest(code="pass", language="python", timeout=45)
        assert req.timeout == 45

    def test_timeout_too_low_raises(self):
        with pytest.raises(Exception):
            CodeExecuteRequest(code="pass", language="python", timeout=0)

    def test_timeout_too_high_raises(self):
        with pytest.raises(Exception):
            CodeExecuteRequest(code="pass", language="python", timeout=61)

    def test_empty_code_raises(self):
        with pytest.raises(Exception):
            CodeExecuteRequest(code="", language="python")


# ---------------------------------------------------------------------------
# get_tailscale_ip
# ---------------------------------------------------------------------------

class TestGetTailscaleIp:
    def test_returns_ip_from_tailscale(self):
        mock_result = MagicMock()
        mock_result.stdout = "100.1.2.3\n"
        with patch("subprocess.run", return_value=mock_result):
            ip = get_tailscale_ip()
        assert ip == "100.1.2.3"

    def test_falls_back_on_error(self):
        with patch("subprocess.run", side_effect=Exception("tailscale not found")):
            ip = get_tailscale_ip()
        # Should return a fallback string, not raise
        assert isinstance(ip, str)

    def test_falls_back_on_subprocess_error(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "tailscale")):
            ip = get_tailscale_ip()
        assert isinstance(ip, str)
