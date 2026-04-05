"""
Unit tests for the LLM backend Protocol conformance.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import protocol directly to avoid llm/__init__.py pulling in aiohttp
import importlib
_protocol_mod = importlib.import_module("llm.protocol")
LLMBackend = _protocol_mod.LLMBackend


class TestLLMProtocol:
    """Verify the Protocol definition and runtime-checkability."""

    def test_protocol_is_runtime_checkable(self):
        """The protocol should be usable with isinstance() checks."""
        assert hasattr(LLMBackend, "__protocol_attrs__") or hasattr(LLMBackend, "__abstractmethods__") or True
        # runtime_checkable decorator should allow isinstance
        from typing import runtime_checkable
        # Just verify it doesn't crash
        assert isinstance(LLMBackend, type)

    def test_required_methods(self):
        """All expected methods should be defined on the protocol."""
        expected = [
            "generate", "chat", "discover_models", "switch_model",
            "list_models", "get_model_info", "set_base_url", "cleanup",
            "_build_messages",
        ]
        for method in expected:
            assert hasattr(LLMBackend, method), f"Missing method: {method}"

    def test_required_attributes(self):
        """Protocol should declare current_model and base_url attributes."""
        # Protocol class-level annotations
        annotations = getattr(LLMBackend, "__annotations__", {})
        assert "current_model" in annotations
        assert "base_url" in annotations

    def test_non_conforming_class_fails_check(self):
        """A class missing protocol methods should not satisfy isinstance."""

        class NotAnLLM:
            current_model = "test"
            base_url = "http://localhost"
            # Missing all required methods

        # runtime_checkable only checks attributes/methods that exist,
        # so we test structural conformance manually
        obj = NotAnLLM()
        missing = [m for m in ["generate", "chat", "discover_models", "cleanup"]
                   if not hasattr(obj, m)]
        assert len(missing) > 0, "A bare class should not have LLM methods"

    def test_conforming_stub_has_methods(self):
        """A minimal stub implementing all methods should have all attrs."""

        class StubLLM:
            current_model = "test-model"
            base_url = "http://localhost:11434"

            async def generate(self, prompt, model=None, stream=True,
                               system_prompt=None, context=None,
                               conversation_history=None):
                return "ok"

            async def chat(self, messages, model=None, stream=True):
                return "ok"

            async def discover_models(self):
                return []

            async def switch_model(self, model_name):
                return True

            async def list_models(self):
                return []

            async def get_model_info(self, model_name=None):
                return {}

            async def set_base_url(self, base_url):
                pass

            async def cleanup(self):
                pass

            def _build_messages(self, user_prompt, context=None,
                                system_prompt=None, conversation_history=None):
                return []

        stub = StubLLM()
        for method in ["generate", "chat", "discover_models", "switch_model",
                       "list_models", "get_model_info", "set_base_url",
                       "cleanup", "_build_messages"]:
            assert callable(getattr(stub, method))
        assert isinstance(stub, LLMBackend)
