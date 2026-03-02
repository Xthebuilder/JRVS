"""
VisionModule — public interface for the JRVS vision extension.

Usage from JRVS or any orchestration code:

    from extensions.vision import VisionModule

    vision = VisionModule()
    await vision.initialize()
    await vision.start()                          # non-blocking; runs in background

    description = await vision.describe_frame()  # on-demand single frame
    alerts = await vision.get_alerts()            # consume pending anomaly alerts

    await vision.stop()

Standalone smoke test:
    python -m extensions.vision.vision_module --describe-once
    python -m extensions.vision.vision_module --run
"""
from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from extensions.base import BaseExtension
from extensions.vision.alerts.alert_manager import AlertManager
from extensions.vision.camera.camera_manager import CameraManager
from extensions.vision.camera.frame_processor import FrameProcessor
from extensions.vision.config import vision_config
from extensions.vision.inference.vision_inference import VisionBackend, create_backend
from extensions.vision.memory.anomaly_detector import AnomalyDetector
from extensions.vision.memory.vision_logger import VisionLogger
from extensions.vision.models.schemas import Alert, Observation

logger = logging.getLogger(__name__)


class VisionModule(BaseExtension):
    """
    JRVS vision extension.

    Captures frames from any camera source, runs local visual inference,
    logs observations into JRVS memory, detects anomalies, and surfaces
    alerts back to JRVS for user-facing reasoning.
    """

    def __init__(self, config=None) -> None:
        self._cfg = config or vision_config
        self._camera = CameraManager(self._cfg.camera_source)
        self._processor = FrameProcessor(
            motion_threshold=self._cfg.motion_threshold,
            periodic_interval=self._cfg.periodic_interval,
            max_width=self._cfg.max_width,
        )
        self._backend: Optional[VisionBackend] = None
        self._detector = AnomalyDetector(
            window_size=self._cfg.anomaly_window_size,
            similarity_threshold=self._cfg.anomaly_similarity_threshold,
            alert_threshold=self._cfg.anomaly_alert_threshold,
        )
        self._logger = VisionLogger(log_level=self._cfg.log_level)
        self._alert_mgr = AlertManager(
            queue_size=self._cfg.alerts_queue_size,
            write_to_jrvs_events=self._cfg.alerts_write_to_jrvs_events,
            min_severity=self._cfg.alerts_min_severity,
            alert_threshold=self._cfg.anomaly_alert_threshold,
        )

        self._running = False
        self._capture_task: Optional[asyncio.Task] = None
        self._last_observation: Optional[Observation] = None
        self._frames_processed = 0
        self._start_time: Optional[datetime] = None

        # For embedding anomaly detection we borrow JRVS embeddings if available
        self._embedding_manager = None

    # ------------------------------------------------------------------
    # BaseExtension lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Load all sub-components.  Must be called before start()."""
        logger.info("Initializing VisionModule (backend=%s, source=%s)",
                    self._cfg.inference_backend, self._cfg.camera_source)

        # Start camera reader thread
        self._camera.open()

        # Load inference backend
        self._backend = create_backend(self._cfg)
        await self._backend.initialize()

        # Connect to JRVS memory
        await self._logger.initialize()
        await self._alert_mgr.initialize()

        # Optionally borrow JRVS embedding_manager for richer anomaly scoring
        try:
            import sys
            from pathlib import Path
            jrvs_root = str(Path(__file__).parent.parent.parent)
            if jrvs_root not in sys.path:
                sys.path.insert(0, jrvs_root)
            from rag.embeddings import embedding_manager
            self._embedding_manager = embedding_manager
            logger.debug("VisionModule using JRVS embedding_manager for anomaly scoring.")
        except ImportError:
            logger.debug("JRVS embedding_manager not available; using fallback anomaly scoring.")

        logger.info("VisionModule initialized.")

    async def start(self) -> None:
        """Begin background capture + inference loop (non-blocking)."""
        if self._running:
            logger.warning("VisionModule already running.")
            return
        if self._backend is None:
            raise RuntimeError("Call initialize() before start().")
        self._running = True
        self._start_time = datetime.now()
        self._capture_task = asyncio.create_task(
            self._capture_loop(), name="vision-capture-loop"
        )
        logger.info("VisionModule started.")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
        self._camera.close()
        if hasattr(self._backend, "close"):
            await self._backend.close()
        logger.info("VisionModule stopped. Frames processed: %d", self._frames_processed)

    def is_running(self) -> bool:
        return self._running and (
            self._capture_task is not None and not self._capture_task.done()
        )

    def status(self) -> Dict[str, Any]:
        last_ts = (
            self._last_observation.timestamp.isoformat()
            if self._last_observation else None
        )
        last_desc = (
            self._last_observation.description[:80]
            if self._last_observation else None
        )
        return {
            "running": self.is_running(),
            "camera_source": str(self._cfg.camera_source),
            "inference_backend": self._cfg.inference_backend,
            "frames_processed": self._frames_processed,
            "alerts_pending": self._alert_mgr.pending_count(),
            "last_observation_at": last_ts,
            "last_description": last_desc,
            "uptime_seconds": (
                (datetime.now() - self._start_time).total_seconds()
                if self._start_time else 0
            ),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def describe_frame(self) -> str:
        """
        Capture one frame immediately and return a description.
        Does NOT affect the background loop state.
        """
        if self._backend is None:
            raise RuntimeError("Call initialize() first.")
        frame = self._camera.read_frame()
        if frame is None:
            return "[no frame available from camera]"
        resized = self._processor._resize(frame)
        return await self._backend.describe(resized, self._cfg.inference_prompt)

    async def get_alerts(self) -> List[Alert]:
        """Drain and return all pending anomaly alerts."""
        return await self._alert_mgr.get_alerts()

    # ------------------------------------------------------------------
    # Internal capture loop
    # ------------------------------------------------------------------

    async def _capture_loop(self) -> None:
        interval = 1.0 / max(self._cfg.fps_capture, 0.1)
        logger.debug("Capture loop started (interval=%.2fs)", interval)
        while self._running:
            try:
                await self._process_frame()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Capture loop error: %s", exc, exc_info=True)
            await asyncio.sleep(interval)

    async def _process_frame(self) -> None:
        frame = self._camera.read_frame()
        if frame is None:
            return

        interesting_frame, motion_score = self._processor.process(frame)
        if interesting_frame is None:
            return

        # Run inference
        description = await self._backend.describe(
            interesting_frame, self._cfg.inference_prompt
        )
        if not description or description.startswith("["):
            return  # Backend error/offline

        self._frames_processed += 1
        now = datetime.now()

        # Get embedding for anomaly detection
        embedding = await self._get_embedding(description)

        # Detect anomalies
        anomaly = None
        if self._cfg.anomaly_enabled and embedding is not None:
            anomaly = self._detector.update(embedding, description, now)

        # Build observation record
        observation = Observation(
            timestamp=now,
            description=description,
            camera_source=str(self._cfg.camera_source),
            motion_score=motion_score,
            embedding=embedding,
            anomaly=anomaly,
        )
        self._last_observation = observation

        # Persist to JRVS memory
        await self._logger.log(observation)

        # Surface anomaly alerts
        if anomaly:
            await self._alert_mgr.push(anomaly)

        logger.debug(
            "Frame processed: motion=%.3f | anomaly=%s | %s",
            motion_score,
            f"{anomaly.score:.2f}" if anomaly else "none",
            description[:60],
        )

    async def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding vector for anomaly scoring; falls back to None."""
        if self._embedding_manager is None:
            return None
        try:
            vectors = await self._embedding_manager.encode_text([text], is_query=False)
            return vectors[0]
        except Exception:
            return None


# ---------------------------------------------------------------------------
# __main__ — smoke tests
# ---------------------------------------------------------------------------
async def _smoke_test_describe() -> None:
    """Capture one frame, describe it, print result."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    v = VisionModule()
    await v.initialize()
    print("\nDescribing current camera frame…\n")
    desc = await v.describe_frame()
    print(f"  {desc}\n")
    await v.stop()


async def _smoke_test_run() -> None:
    """Run the vision loop until Ctrl-C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    v = VisionModule()
    await v.initialize()
    await v.start()
    print("VisionModule running. Press Ctrl-C to stop.\n")

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()
    loop.add_signal_handler(signal.SIGINT, stop_event.set)
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)

    try:
        while not stop_event.is_set():
            await asyncio.sleep(5)
            print("Status:", v.status())
            alerts = await v.get_alerts()
            for a in alerts:
                print(f"  ALERT [{a.severity.upper()}]: {a.title}")
    finally:
        await v.stop()


if __name__ == "__main__":
    import sys as _sys
    if "--describe-once" in _sys.argv:
        asyncio.run(_smoke_test_describe())
    else:
        asyncio.run(_smoke_test_run())
