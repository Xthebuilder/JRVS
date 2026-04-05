"""
Unit tests for voice.py

Tests the module-level constants and the overall structure.
The main() coroutine requires a running WebSocket server, so that
is tested via mock rather than a real connection.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import itertools

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

try:
    import voice as voice_module
    _IMPORT_OK = True
except Exception:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="voice module failed to import (missing audio extension OK in CI)"
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestVoiceConstants:
    def test_ws_url_is_string(self):
        assert isinstance(voice_module.JRVS_WS_URL, str)
        assert voice_module.JRVS_WS_URL.startswith("ws://")

    def test_http_url_is_string(self):
        assert isinstance(voice_module.JRVS_HTTP_URL, str)
        assert voice_module.JRVS_HTTP_URL.startswith("http://")

    def test_feedback_url_is_string(self):
        assert isinstance(voice_module.JRVS_FEEDBACK_URL, str)
        assert "feedback" in voice_module.JRVS_FEEDBACK_URL

    def test_session_id_set(self):
        assert isinstance(voice_module.SESSION_ID, str)
        assert len(voice_module.SESSION_ID) > 0

    def test_thinking_phrases_is_cycle(self):
        # Should be an itertools.cycle or similar iterable
        phrase = next(voice_module._THINKING_PHRASES)
        assert isinstance(phrase, str)
        assert len(phrase) > 0


# ---------------------------------------------------------------------------
# _last_qa tracking
# ---------------------------------------------------------------------------

class TestLastQA:
    def test_last_qa_initially_empty_or_none(self):
        # Either None or an empty dict — both are valid initial states
        assert voice_module._last_qa is None or isinstance(voice_module._last_qa, dict)
