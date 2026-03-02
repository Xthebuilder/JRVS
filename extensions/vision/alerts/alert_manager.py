"""
AlertManager — queues vision alerts and surfaces them to JRVS.

Alerts are delivered two ways:
  1. asyncio.Queue  — JRVS orchestration code calls get_alerts() to consume them
  2. JRVS events table — written via core.calendar so /calendar shows them
                         and they appear in RAG context for future queries

Severity filter: only alerts at or above min_severity are enqueued.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import List

from extensions.vision.models.schemas import Alert, Anomaly

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}
_JRVS_ROOT = Path(__file__).parent.parent.parent.parent


def _ensure_jrvs_on_path() -> bool:
    root = str(_JRVS_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import core.calendar  # noqa: F401
        return True
    except ImportError:
        return False


class AlertManager:
    """Buffers vision alerts and writes them to JRVS events table."""

    def __init__(
        self,
        queue_size: int = 50,
        write_to_jrvs_events: bool = True,
        min_severity: str = "medium",
        alert_threshold: float = 0.85,
    ) -> None:
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=queue_size)
        self._write_to_jrvs = write_to_jrvs_events
        self._min_severity = min_severity
        self._alert_threshold = alert_threshold
        self._calendar = None
        self._jrvs_available = False

    async def initialize(self) -> None:
        """Connect to JRVS calendar for writing alerts to the events table."""
        if not self._write_to_jrvs:
            return
        if not _ensure_jrvs_on_path():
            logger.warning("AlertManager: JRVS not found; alerts will queue-only.")
            return
        try:
            from core.calendar import calendar
            await calendar.initialize()
            self._calendar = calendar
            self._jrvs_available = True
            logger.info("AlertManager connected to JRVS events table.")
        except Exception as exc:
            logger.error("AlertManager JRVS init error: %s", exc)

    async def push(self, anomaly: Anomaly) -> None:
        """
        Evaluate anomaly and emit an Alert if it meets threshold and severity.

        Args:
            anomaly: Anomaly detected by AnomalyDetector
        """
        if anomaly.score < self._alert_threshold:
            return

        alert = Alert.from_anomaly(anomaly, self._alert_threshold)

        # Filter by minimum severity
        if _SEVERITY_ORDER.get(alert.severity, 0) < _SEVERITY_ORDER.get(self._min_severity, 0):
            return

        # Add to queue (non-blocking; drop oldest if full)
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        await self._queue.put(alert)
        logger.info("Alert queued [%s]: %s", alert.severity.upper(), alert.title)

        # Write to JRVS events table
        if self._jrvs_available and self._calendar:
            await self._write_event(alert)

    async def get_alerts(self) -> List[Alert]:
        """Drain and return all pending alerts (non-blocking)."""
        alerts = []
        while not self._queue.empty():
            try:
                alerts.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return alerts

    def pending_count(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _write_event(self, alert: Alert) -> None:
        try:
            await self._calendar.add_event(
                title=alert.title,
                event_date=alert.anomaly.timestamp,
                description=alert.details,
                reminder_minutes=0,
            )
            logger.debug("Alert written to JRVS events table: %s", alert.title)
        except Exception as exc:
            logger.error("Failed to write alert to JRVS events: %s", exc)
