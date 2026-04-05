"""
Unit tests for rag/embeddings.py

All model-loading is mocked — no GPU or sentence_transformers required.
"""

import sys
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.embeddings import EmbeddingManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_model(dim=768):
    """Minimal SentenceTransformer mock."""
    model = MagicMock()
    model.encode = MagicMock(return_value=np.ones((1, dim), dtype=np.float32))
    model.get_sentence_embedding_dimension = MagicMock(return_value=dim)
    return model


async def _initialized_manager(dim=768):
    mgr = EmbeddingManager(model_name="mock-model")
    mgr._model = _mock_model(dim)
    return mgr


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestEmbeddingManagerInit:
    def test_model_name_stored(self):
        mgr = EmbeddingManager(model_name="test-model")
        assert mgr.model_name == "test-model"

    def test_model_initially_none(self):
        mgr = EmbeddingManager()
        assert mgr._model is None

    def test_cache_starts_empty(self):
        mgr = EmbeddingManager()
        assert mgr.get_cache_size() == 0

    def test_bge_model_sets_query_prefix(self):
        mgr = EmbeddingManager(model_name="BAAI/bge-base-en")
        assert len(mgr._query_prefix) > 0

    def test_non_bge_model_no_query_prefix(self):
        mgr = EmbeddingManager(model_name="all-MiniLM-L6-v2")
        assert mgr._query_prefix == ""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class TestEmbeddingCache:
    def test_clear_cache_empties(self):
        mgr = EmbeddingManager()
        mgr._embedding_cache["key"] = np.zeros(768)
        mgr.clear_cache()
        assert mgr.get_cache_size() == 0

    def test_get_cache_size(self):
        mgr = EmbeddingManager()
        mgr._embedding_cache["k1"] = np.zeros(768)
        mgr._embedding_cache["k2"] = np.zeros(768)
        assert mgr.get_cache_size() == 2


# ---------------------------------------------------------------------------
# get_embedding_dimension
# ---------------------------------------------------------------------------

class TestGetEmbeddingDimension:
    def test_returns_default_when_no_model(self):
        mgr = EmbeddingManager()
        dim = mgr.get_embedding_dimension()
        assert dim == 768  # Default

    def test_returns_model_dim_when_loaded(self):
        mgr = EmbeddingManager()
        mgr._model = _mock_model(dim=384)
        dim = mgr.get_embedding_dimension()
        assert dim == 384


# ---------------------------------------------------------------------------
# encode_text (with mocked model)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEncodeText:
    async def test_encode_single_string(self):
        mgr = await _initialized_manager()
        result = await mgr.encode_text("hello world")
        assert isinstance(result, np.ndarray)

    async def test_encode_list_of_strings(self):
        mgr = await _initialized_manager()
        model = mgr._model
        model.encode = MagicMock(return_value=np.ones((3, 768), dtype=np.float32))
        result = await mgr.encode_text(["a", "b", "c"])
        assert isinstance(result, np.ndarray)

    async def test_result_cached_after_first_call(self):
        mgr = await _initialized_manager()
        await mgr.encode_text("cache me")
        size_after_first = mgr.get_cache_size()
        await mgr.encode_text("cache me")  # Second call — should hit cache
        assert mgr.get_cache_size() == size_after_first

    async def test_model_encode_called_for_cache_miss(self):
        mgr = await _initialized_manager()
        await mgr.encode_text("fresh text " + str(id(mgr)))
        mgr._model.encode.assert_called()

    async def test_query_prefix_applied_for_bge_is_query(self):
        mgr = EmbeddingManager(model_name="BAAI/bge-base-en")
        mgr._model = _mock_model()
        await mgr.encode_text("what is AI?", is_query=True)
        call_args = mgr._model.encode.call_args[0][0]
        assert "Represent" in call_args or "searching" in call_args


# ---------------------------------------------------------------------------
# encode_chunks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEncodeChunks:
    async def test_returns_list_of_arrays(self):
        mgr = await _initialized_manager()
        mgr._model.encode = MagicMock(return_value=np.ones((2, 768), dtype=np.float32))
        result = await mgr.encode_chunks(["chunk one", "chunk two"])
        assert isinstance(result, list)
        assert all(isinstance(r, np.ndarray) for r in result)

    async def test_empty_chunks_returns_empty(self):
        mgr = await _initialized_manager()
        result = await mgr.encode_chunks([])
        assert result == []


# ---------------------------------------------------------------------------
# similarity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSimilarity:
    async def test_identical_texts_high_similarity(self):
        mgr = await _initialized_manager()
        vec = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        mgr._model.encode = MagicMock(return_value=vec)
        sim = await mgr.similarity("text", "text")
        assert sim >= 0.99

    async def test_similarity_in_valid_range(self):
        mgr = await _initialized_manager()
        # Model returns same vec for both — similarity = 1.0
        sim = await mgr.similarity("a", "b")
        assert -1.0 <= sim <= 1.0
