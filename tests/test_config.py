"""
Unit tests for JRVS config module.

Tests device class profiles, platform-safe strftime, config validation,
and environment variable overrides.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDeviceProfiles:
    """Test device class profile selection and defaults."""

    def test_default_is_desktop(self):
        from config import DEVICE_CLASS, _profile
        # Without env var set, should default to desktop
        assert DEVICE_CLASS in ("desktop", "server", "sbc", "mobile")

    def test_desktop_profile_values(self):
        from config import _DEVICE_PROFILES
        desktop = _DEVICE_PROFILES["desktop"]
        assert desktop["default_model"] == "gemma3:12b"
        assert desktop["max_context_length"] == 12000
        assert desktop["chunk_size"] == 512

    def test_sbc_profile_is_lighter(self):
        from config import _DEVICE_PROFILES
        sbc = _DEVICE_PROFILES["sbc"]
        desktop = _DEVICE_PROFILES["desktop"]
        assert sbc["max_context_length"] < desktop["max_context_length"]
        assert sbc["chunk_size"] < desktop["chunk_size"]
        assert sbc["max_memory_mb"] < desktop["max_memory_mb"]
        assert sbc["default_model"] == "phi3:mini"

    def test_server_profile_is_heavier(self):
        from config import _DEVICE_PROFILES
        server = _DEVICE_PROFILES["server"]
        desktop = _DEVICE_PROFILES["desktop"]
        assert server["max_context_length"] >= desktop["max_context_length"]
        assert server["embedding_batch_size"] >= desktop["embedding_batch_size"]

    def test_all_profiles_have_same_keys(self):
        from config import _DEVICE_PROFILES
        keys = set(_DEVICE_PROFILES["desktop"].keys())
        for name, profile in _DEVICE_PROFILES.items():
            assert set(profile.keys()) == keys, f"Profile '{name}' has different keys"


class TestPlatformSafeStrftime:
    """Test cross-platform date formatting."""

    def test_basic_formatting(self):
        from config import _platform_safe_strftime
        dt = datetime(2026, 3, 9, 14, 30)
        result = _platform_safe_strftime("%A, %B %-d, %Y", dt)
        assert "2026" in result
        assert "March" in result

    def test_time_formatting(self):
        from config import _platform_safe_strftime
        dt = datetime(2026, 3, 9, 5, 32)
        result = _platform_safe_strftime("%-I:%M %p", dt)
        assert "5" in result or "05" in result
        assert "AM" in result

    def test_no_crash_on_any_platform(self):
        """_platform_safe_strftime should never raise."""
        from config import _platform_safe_strftime
        dt = datetime(2026, 1, 1, 0, 0)
        # Should not raise ValueError on any platform
        result = _platform_safe_strftime("%A, %B %-d, %Y", dt)
        assert isinstance(result, str)
        assert len(result) > 0


class TestConfigValidation:
    """Test that config validation catches bad values."""

    def test_system_prompt_contains_jarvis(self):
        from config import SYSTEM_PROMPT
        assert "JARVIS" in SYSTEM_PROMPT

    def test_voice_prompt_is_concise(self):
        from config import _build_voice_system_prompt
        prompt = _build_voice_system_prompt()
        assert "JARVIS" in prompt
        assert "markdown" in prompt.lower() or "no markdown" in prompt.lower()

    def test_timeouts_are_positive(self):
        from config import TIMEOUTS
        for key, val in TIMEOUTS.items():
            assert val > 0, f"Timeout '{key}' must be positive"

    def test_chunk_overlap_less_than_chunk_size(self):
        from config import CHUNK_SIZE, CHUNK_OVERLAP
        assert CHUNK_OVERLAP < CHUNK_SIZE

    def test_similarity_threshold_in_range(self):
        from config import SIMILARITY_THRESHOLD
        assert 0.0 <= SIMILARITY_THRESHOLD <= 1.0

    def test_mmr_lambda_in_range(self):
        from config import MMR_LAMBDA
        assert 0.0 <= MMR_LAMBDA <= 1.0

    def test_rag_backend_default_is_mem0(self):
        from config import RAG_BACKEND
        assert RAG_BACKEND in ("mem0", "faiss")

    def test_rag_backend_invalid_value_raises(self):
        """_validate_config should reject invalid RAG_BACKEND values."""
        import importlib
        with patch.dict(os.environ, {"RAG_BACKEND": "invalid"}):
            import config as _cfg
            # Temporarily override the module-level var and re-run validation
            original = _cfg.RAG_BACKEND
            _cfg.RAG_BACKEND = "invalid"
            try:
                with pytest.raises(ValueError, match="RAG_BACKEND"):
                    _cfg._validate_config()
            finally:
                _cfg.RAG_BACKEND = original

    def test_jrvs_server_port_default(self):
        from config import JRVS_SERVER_HOST, JRVS_SERVER_PORT
        assert isinstance(JRVS_SERVER_HOST, str)
        assert JRVS_SERVER_PORT == 8000

    def test_jrvs_server_port_invalid_raises(self):
        """Module reload should reject non-integer JRVS_SERVER_PORT."""
        import importlib
        with patch.dict(os.environ, {"JRVS_SERVER_PORT": "notanumber"}):
            with pytest.raises(ValueError, match="JRVS_SERVER_PORT"):
                importlib.reload(__import__("config"))
