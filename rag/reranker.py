"""
Cross-encoder re-ranker for JRVS retrieval pipeline.

Uses 'cross-encoder/ms-marco-MiniLM-L-6-v2' — a small, fast model trained on
MS MARCO passage ranking.  Unlike bi-encoder embeddings (which score query and
document independently), a cross-encoder sees (query, document) together, giving
much more accurate relevance scores at the cost of being slower.  We only call it
on a small candidate set (RERANK_CANDIDATES) so the latency stays acceptable.

Degrades gracefully: if the model is not installed the reranker logs a warning
and returns the original candidates unchanged.
"""
import asyncio
import logging
from typing import Dict, List, Tuple

log = logging.getLogger(__name__)

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self):
        self._model = None
        self._available: bool | None = None  # None = not yet checked

    async def initialize(self) -> bool:
        """Lazy-load the cross-encoder. Returns True if available."""
        if self._available is not None:
            return self._available

        try:
            from sentence_transformers import CrossEncoder
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None, lambda: CrossEncoder(_MODEL_NAME)
            )
            self._available = True
            log.info("[Reranker] Loaded %s", _MODEL_NAME)
        except Exception as e:
            log.warning("[Reranker] Not available (%s) — falling back to original ranking", e)
            self._available = False

        return self._available

    async def rerank(
        self,
        query: str,
        candidates: List[Tuple[str, float, Dict]],
        top_k: int,
    ) -> List[Tuple[str, float, Dict]]:
        """
        Re-rank *candidates* using the cross-encoder.

        Parameters
        ----------
        query      : the user's search query
        candidates : list of (text, score, metadata) from FAISS/hybrid search
        top_k      : how many results to return after re-ranking

        Returns
        -------
        Re-ordered list of (text, cross_encoder_score, metadata), length ≤ top_k.
        Falls back to original order if the model is unavailable.
        """
        if len(candidates) <= 1:
            return candidates[:top_k]

        available = await self.initialize()
        if not available:
            return candidates[:top_k]

        texts = [c[0] for c in candidates]
        pairs = [[query, t] for t in texts]

        try:
            loop = asyncio.get_event_loop()
            scores = await loop.run_in_executor(
                None, lambda: self._model.predict(pairs)
            )
        except Exception as e:
            log.error("[Reranker] predict() failed: %s", e)
            return candidates[:top_k]

        # Pair each score with its candidate and sort descending
        scored = sorted(
            zip(scores, candidates),
            key=lambda x: float(x[0]),
            reverse=True,
        )

        return [
            (text, float(score), meta)
            for score, (text, _, meta) in scored[:top_k]
        ]


# Global reranker instance
reranker = CrossEncoderReranker()
