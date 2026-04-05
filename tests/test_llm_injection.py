"""
Unit tests for LLM client injection — verifies that all three classes
using set_llm_client() / _client raise RuntimeError when no client
has been injected, and return the injected client when one is provided.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_gateway.agent import MCPAgent
from mcp_gateway.coding_agent import JARCORE
from core.goal_scheduler import GoalScheduler


# ---------------------------------------------------------------------------
# MCPAgent
# ---------------------------------------------------------------------------

class TestMCPAgentLLMInjection:
    """Verify MCPAgent._client raises without injection and works with it."""

    def test_client_raises_without_injection(self):
        agent = MCPAgent()
        with pytest.raises(RuntimeError, match="LLM client not injected"):
            _ = agent._client

    def test_client_returns_injected_mock(self):
        agent = MCPAgent()
        mock_llm = MagicMock()
        agent.set_llm_client(mock_llm)
        assert agent._client is mock_llm

    def test_direct_field_assignment_works(self):
        """Existing test helpers assign _llm_client directly."""
        agent = MCPAgent()
        mock_llm = MagicMock()
        agent._llm_client = mock_llm
        assert agent._client is mock_llm


# ---------------------------------------------------------------------------
# JARCORE
# ---------------------------------------------------------------------------

class TestJARCORELLMInjection:
    """Verify JARCORE._client raises without injection and works with it."""

    def test_client_raises_without_injection(self, tmp_path):
        jc = JARCORE(workspace_root=str(tmp_path))
        with pytest.raises(RuntimeError, match="LLM client not injected"):
            _ = jc._client

    def test_client_returns_injected_mock(self, tmp_path):
        jc = JARCORE(workspace_root=str(tmp_path))
        mock_llm = MagicMock()
        jc.set_llm_client(mock_llm)
        assert jc._client is mock_llm

    def test_direct_field_assignment_works(self, tmp_path):
        """Mirrors the _jarcore() helper in test_jarcore.py."""
        jc = JARCORE(workspace_root=str(tmp_path))
        mock_llm = MagicMock()
        jc._llm_client = mock_llm
        assert jc._client is mock_llm


# ---------------------------------------------------------------------------
# GoalScheduler
# ---------------------------------------------------------------------------

class TestGoalSchedulerLLMInjection:
    """Verify GoalScheduler._client raises without injection and works with it."""

    def test_client_raises_without_injection(self):
        gs = GoalScheduler()
        with pytest.raises(RuntimeError, match="LLM client not injected"):
            _ = gs._client

    def test_client_returns_injected_mock(self):
        gs = GoalScheduler()
        mock_llm = MagicMock()
        gs.set_llm_client(mock_llm)
        assert gs._client is mock_llm

    def test_direct_field_assignment_works(self):
        gs = GoalScheduler()
        mock_llm = MagicMock()
        gs._llm_client = mock_llm
        assert gs._client is mock_llm
