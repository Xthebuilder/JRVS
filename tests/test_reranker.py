"""
Unit tests for rag/reranker.py

CrossEncoder model is mocked — no model download required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.reranker import CrossEncoderReranker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_cross_encoder(scores=None):
    model = MagicMock()
    model.predict = MagicMock(return_value=scores or [0.9, 0.3, 0.7])
    return model


def _candidates(n=3):
    return [(f"text {i}", float(i) * 0.1, {"id": i}) for i in range(n)]


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestRerankerInit:
    def test_model_initially_none(self):
        r = CrossEncoderReranker()
        assert r._model is None

    def test_available_initially_none(self):
        r = CrossEncoderReranker()
        assert r._available is None


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestInitialize:
    async def test_initializes_with_mock_model(self):
        r = CrossEncoderReranker()
        with patch("rag.reranker.CrossEncoder", return_value=_mock_cross_encoder()):
            available = await r.initialize()
        assert available is True
        assert r._model is not None

    async def test_graceful_degradation_on_import_error(self):
        r = CrossEncoderReranker()
        with patch("rag.reranker.CrossEncoder", side_effect=Exception("no model")):
            available = await r.initialize()
        assert available is False
        assert r._available is False

    async def test_idempotent_second_init(self):
        r = CrossEncoderReranker()
        r._available = True
        r._model = _mock_cross_encoder()
        available = await r.initialize()
        assert available is True


# ---------------------------------------------------------------------------
# rerank
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRerank:
    async def test_returns_reranked_order(self):
        r = CrossEncoderReranker()
        r._available = True
        r._model = _mock_cross_encoder(scores=[0.1, 0.9, 0.5])
        candidates = _candidates(3)
        result = await r.rerank("query", candidates, top_k=3)
        # Highest score (0.9) = candidate index 1 should be first
        assert result[0][0] == "text 1"

    async def test_top_k_limits_results(self):
        r = CrossEncoderReranker()
        r._available = True
        r._model = _mock_cross_encoder(scores=[0.3, 0.9, 0.6])
        candidates = _candidates(3)
        result = await r.rerank("query", candidates, top_k=2)
        assert len(result) == 2

    async def test_fallback_when_unavailable(self):
        r = CrossEncoderReranker()
        r._available = False
        candidates = _candidates(3)
        result = await r.rerank("query", candidates, top_k=3)
        # Falls back to original order
        assert len(result) == 3
        assert result[0][0] == candidates[0][0]

    async def test_fallback_when_not_initialized(self):
        r = CrossEncoderReranker()
        # _available is None (not yet initialized)
        candidates = _candidates(2)
        result = await r.rerank("query", candidates, top_k=2)
        assert len(result) == 2

    async def test_returns_tuples_with_score_and_metadata(self):
        r = CrossEncoderReranker()
        r._available = True
        r._model = _mock_cross_encoder(scores=[0.8, 0.2])
        candidates = [("text A", 0.5, {"source": "x"}), ("text B", 0.3, {"source": "y"})]
        result = await r.rerank("q", candidates, top_k=2)
        assert len(result[0]) == 3
        text, score, meta = result[0]
        assert isinstance(text, str)
        assert isinstance(score, float)
        assert isinstance(meta, dict)

    async def test_empty_candidates_returns_empty(self):
        r = CrossEncoderReranker()
        r._available = True
        r._model = _mock_cross_encoder(scores=[])
        result = await r.rerank("query", [], top_k=5)
        assert result == []
