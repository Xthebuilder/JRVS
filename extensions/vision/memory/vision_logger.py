"""
VisionLogger — persists vision observations into JRVS memory.

Each observation is written as a JRVS document so the full RAG pipeline
(hybrid FAISS + FTS5 search, cross-encoder reranking, MMR) can retrieve it
when the user asks "What did you see earlier?" or "Was anyone in the room?"

Writes to:
  - documents table      (title, content, content_type, metadata)
  - document_chunks      (chunked text for FTS5)
  - chunks_fts           (virtual FTS5 table — auto-populated via trigger)
  - vector_map / FAISS   (embeddings via JRVS's own embedding_manager)

All imports of JRVS modules use a path-insertion guard so this file works
even when run from outside the JRVS venv.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JRVS integration bootstrap
# ---------------------------------------------------------------------------
_JRVS_ROOT = Path(__file__).parent.parent.parent.parent  # extensions/../../..

def _ensure_jrvs_on_path() -> bool:
    """Add JRVS root to sys.path if not already present.  Returns True on success."""
    root = str(_JRVS_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import core.database  # noqa: F401
        return True
    except ImportError as exc:
        logger.error(
            "Cannot import JRVS core modules from %s: %s. "
            "Observations will not be persisted.",
            root, exc,
        )
        return False


class VisionLogger:
    """Writes vision observations into JRVS's SQLite + FAISS memory."""

    CONTENT_TYPE = "vision_observation"

    def __init__(self, log_level: str = "scene") -> None:
        """
        Args:
            log_level: "all" | "scene" | "anomaly"
              all     → persist every inference
              scene   → persist only when scene changed meaningfully
              anomaly → persist only anomalous observations
        """
        self.log_level = log_level
        self._jrvs_available = False
        self._db = None
        self._vector_store = None
        self._last_description: Optional[str] = None

    async def initialize(self) -> None:
        """Import JRVS singletons.  Safe to call even if JRVS is unavailable."""
        if not _ensure_jrvs_on_path():
            return
        try:
            from core.database import db
            from rag.vector_store import vector_store

            await db.initialize()
            self._db = db
            self._vector_store = vector_store
            self._jrvs_available = True
            logger.info("VisionLogger connected to JRVS memory.")
        except Exception as exc:
            logger.error("VisionLogger JRVS init error: %s", exc)

    async def log(self, observation) -> None:
        """
        Persist an Observation to JRVS memory (if it passes the log_level filter).

        Args:
            observation: extensions.vision.models.schemas.Observation
        """
        if not self._should_log(observation):
            return

        doc_url = f"vision://observation/{int(observation.timestamp.timestamp() * 1000)}"
        doc_title = f"Vision @ {observation.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        metadata = {
            "camera_source": str(observation.camera_source),
            "motion_score": round(observation.motion_score, 4),
            "anomaly_score": round(observation.anomaly.score, 4) if observation.anomaly else 0.0,
            "anomaly_reason": observation.anomaly.reason if observation.anomaly else "",
            "timestamp": observation.timestamp.isoformat(),
        }

        if self._jrvs_available and self._db:
            try:
                doc_id = await self._db.add_document(
                    url=doc_url,
                    title=doc_title,
                    content=observation.description,
                    content_type=self.CONTENT_TYPE,
                    metadata=metadata,
                )
                # Add to FAISS via JRVS vector_store (handles embedding internally)
                if self._vector_store and doc_id:
                    await self._vector_store.add_documents(
                        texts=[observation.description],
                        metadata=[{**metadata, "doc_id": doc_id, "type": "vision_observation"}],
                    )
                observation.doc_id = doc_url
                logger.debug("Logged observation to JRVS memory: %s", doc_url)
            except Exception as exc:
                logger.error("Failed to write observation to JRVS memory: %s", exc)
        else:
            # Fallback: structured log line so the observation isn't lost entirely
            logger.info(
                "[VISION] %s | motion=%.3f | %s",
                doc_title,
                observation.motion_score,
                observation.description,
            )

        self._last_description = observation.description

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _should_log(self, observation) -> bool:
        """Apply log_level filter."""
        if self.log_level == "all":
            return True
        if self.log_level == "anomaly":
            return observation.anomaly is not None
        # "scene" — log when description changed meaningfully or no baseline yet
        if self._last_description is None:
            return True
        # Simple heuristic: log if descriptions share < 60% of words
        prev_words = set(self._last_description.lower().split())
        curr_words = set(observation.description.lower().split())
        if not prev_words:
            return True
        overlap = len(prev_words & curr_words) / len(prev_words | curr_words)
        return overlap < 0.6
