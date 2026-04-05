"""Shared pytest fixtures for JRVS tests."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary database path."""
    return str(tmp_path / "test_jarvis.db")


@pytest.fixture
def mock_ollama_client():
    """Mock OllamaClient for unit tests."""
    client = AsyncMock()
    client.current_model = "test-model:latest"
    client.base_url = "http://localhost:11434"
    client._available_models = ["test-model:latest", "another-model:7b"]
    client.generate.return_value = "Test response from JRVS."
    client.chat.return_value = "Test chat response."
    client.discover_models.return_value = ["test-model:latest", "another-model:7b"]
    client.switch_model.return_value = True
    client.list_models.return_value = [
        {"name": "test-model:latest", "current": True, "size": 0},
    ]
    return client


@pytest.fixture
def mock_rag_retriever():
    """Mock RAG retriever for unit tests."""
    retriever = AsyncMock()
    retriever.retrieve_context.return_value = "Some relevant context from documents."
    retriever.search_documents.return_value = []
    retriever.initialize.return_value = None
    retriever.get_stats.return_value = {"vectors": 0, "documents": 0}
    return retriever


@pytest.fixture
def sample_conversation_history():
    """Sample conversation history for testing."""
    return [
        {"user": "Hello", "assistant": "Hi there! How can I help?"},
        {"user": "What is RAG?", "assistant": "RAG stands for Retrieval-Augmented Generation."},
    ]
