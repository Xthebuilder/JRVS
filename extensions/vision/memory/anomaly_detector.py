"""
AnomalyDetector — identifies deviations from established scene patterns.

Two complementary signals:
  1. Embedding-space drift   — cosine distance between current observation
                               embedding and the rolling baseline mean.
  2. Hour-of-day frequency   — flags objects/scenes appearing at unusual hours
                               based on a 24-bin frequency table built over time.

The detector keeps a circular buffer of the last `window_size` embeddings.
Anomaly score is in [0, 1]; above alert_threshold → Alert.
"""
from __future__ import annotations

import logging
from collections import Counter, deque
from datetime import datetime
from typing import Deque, List, Optional

import numpy as np

from extensions.vision.models.schemas import Anomaly

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Stateful rolling-baseline anomaly detector for vision observations."""

    def __init__(
        self,
        window_size: int = 100,
        similarity_threshold: float = 0.70,
        alert_threshold: float = 0.85,
    ) -> None:
        self.window_size = window_size
        self.similarity_threshold = similarity_threshold
        self.alert_threshold = alert_threshold

        # Rolling embedding buffer (unit-normalized vectors)
        self._buffer: Deque[np.ndarray] = deque(maxlen=window_size)
        self._baseline_mean: Optional[np.ndarray] = None

        # Hour-of-day keyword frequency table: hour → Counter({word: count})
        self._hour_counts: List[Counter] = [Counter() for _ in range(24)]
        self._hour_totals: List[int] = [0] * 24

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        embedding: np.ndarray,
        description: str,
        timestamp: Optional[datetime] = None,
    ) -> Optional[Anomaly]:
        """
        Update internal state with a new observation embedding.

        Returns an Anomaly if score exceeds similarity_threshold, else None.

        Args:
            embedding:   1-D unit-normalized embedding vector
            description: Text description of the observation
            timestamp:   When the observation was captured (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()

        hour = timestamp.hour
        vec = self._normalize(embedding.flatten())

        # Update hour-of-day frequency table
        self._update_hour_table(description, hour)

        # Compute anomaly score before adding to buffer
        score, reason = self._compute_anomaly(vec, description, hour)

        # Add to rolling buffer and recompute baseline
        self._buffer.append(vec)
        self._baseline_mean = np.mean(np.stack(list(self._buffer)), axis=0)

        if score >= self.similarity_threshold:
            logger.info(
                "Anomaly detected (score=%.3f): %s | %s",
                score, reason, description[:80],
            )
            return Anomaly(
                score=score,
                description=description,
                reason=reason,
                timestamp=timestamp,
                hour_bin=hour,
            )
        return None

    def reset(self) -> None:
        """Clear all accumulated state (call on long camera pauses)."""
        self._buffer.clear()
        self._baseline_mean = None
        self._hour_counts = [Counter() for _ in range(24)]
        self._hour_totals = [0] * 24

    @property
    def has_baseline(self) -> bool:
        """True once enough frames have been seen to compute a reliable baseline."""
        return len(self._buffer) >= min(10, self.window_size)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_anomaly(
        self, vec: np.ndarray, description: str, hour: int
    ) -> tuple[float, str]:
        """Compute composite anomaly score and a human-readable reason."""
        if not self.has_baseline or self._baseline_mean is None:
            return 0.0, "building baseline"

        # Signal 1: embedding cosine distance from baseline mean
        baseline_norm = self._normalize(self._baseline_mean)
        cosine_sim = float(np.dot(vec, baseline_norm))
        embedding_dist = 1.0 - cosine_sim  # 0 = identical, 1 = orthogonal

        # Signal 2: hour-of-day unusualness
        hour_score = self._hour_anomaly_score(description, hour)

        # Combine (weighted sum, embedding distance dominates)
        score = 0.7 * embedding_dist + 0.3 * hour_score

        # Build human-readable reason
        reasons = []
        if embedding_dist >= self.similarity_threshold:
            reasons.append(f"scene shift (embedding distance {embedding_dist:.2f})")
        if hour_score >= 0.7:
            reasons.append(f"unusual time of day (hour {hour:02d}:00)")
        reason = "; ".join(reasons) if reasons else f"mild deviation (score {score:.2f})"

        return min(score, 1.0), reason

    def _hour_anomaly_score(self, description: str, hour: int) -> float:
        """Score how unusual this description is for the given hour-of-day."""
        total = self._hour_totals[hour]
        if total < 5:
            return 0.0  # Not enough data for this hour

        words = set(description.lower().split())
        counts = self._hour_counts[hour]
        if not counts:
            return 0.5

        # Fraction of description words that have never appeared at this hour
        unseen = sum(1 for w in words if counts[w] == 0)
        return unseen / len(words) if words else 0.0

    def _update_hour_table(self, description: str, hour: int) -> None:
        words = description.lower().split()
        self._hour_counts[hour].update(words)
        self._hour_totals[hour] += 1

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 1e-9 else vec
