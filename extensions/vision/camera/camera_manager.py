"""
CameraManager — opens and maintains a camera stream.

Supported sources (set via config.yaml or JRVS_VISION_CAMERA_SOURCE):
  0, 1, …            USB / built-in webcam (device index)
  http://IP:4747/video  DroidCam over WiFi (MJPEG HTTP stream)
  rtsp://…           RTSP network camera
  http://…           Any HTTP MJPEG stream

The manager runs a background thread that continuously reads frames into a
one-element buffer so the latest frame is always available without blocking
the async event loop.  On disconnect it reconnects with exponential backoff.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Union

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_RECONNECT_BASE_DELAY = 1.0   # seconds
_RECONNECT_MAX_DELAY  = 30.0  # seconds
_FRAME_TIMEOUT        = 5.0   # seconds before declaring source stale


class CameraManager:
    """Thread-safe camera reader with auto-reconnect."""

    def __init__(self, source: Union[int, str]) -> None:
        self.source = source
        self._cap: Optional[cv2.VideoCapture] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._last_frame_time: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the camera and start the background reader thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._reader_loop, name="vision-camera-reader", daemon=True
        )
        self._thread.start()
        # Wait up to 5 s for first frame
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self._latest_frame is not None:
                logger.info("Camera opened: %s", self.source)
                return
            time.sleep(0.1)
        logger.warning("Camera %s opened but no frame received within 5 s", self.source)

    def close(self) -> None:
        """Stop the reader thread and release the capture device."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap and self._cap.isOpened():
            self._cap.release()
        logger.info("Camera closed: %s", self.source)

    def read_frame(self) -> Optional[np.ndarray]:
        """Return the most recent frame (BGR), or None if unavailable."""
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            # Detect stale stream
            if time.monotonic() - self._last_frame_time > _FRAME_TIMEOUT:
                logger.warning("Camera stream appears stale (no frame for %.0fs)", _FRAME_TIMEOUT)
                return None
            return self._latest_frame.copy()

    @property
    def is_open(self) -> bool:
        return self._running and self._cap is not None and self._cap.isOpened()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> bool:
        """Try to open the capture.  Returns True on success."""
        if self._cap and self._cap.isOpened():
            self._cap.release()
        self._cap = cv2.VideoCapture(self.source)
        if isinstance(self.source, str):
            # Lower buffer for HTTP/RTSP to reduce latency
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self._cap.isOpened():
            logger.info("Connected to camera source: %s", self.source)
            return True
        logger.warning("Could not open camera source: %s", self.source)
        return False

    def _reader_loop(self) -> None:
        """Continuously read frames; reconnect on failure."""
        delay = _RECONNECT_BASE_DELAY
        while self._running:
            if not self._connect():
                time.sleep(delay)
                delay = min(delay * 2, _RECONNECT_MAX_DELAY)
                continue
            delay = _RECONNECT_BASE_DELAY  # reset on successful connect
            while self._running:
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    logger.warning("Frame read failed on %s; reconnecting…", self.source)
                    break
                with self._frame_lock:
                    self._latest_frame = frame
                    self._last_frame_time = time.monotonic()
        if self._cap:
            self._cap.release()
